from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    Booking,
    BookingCancellationRequest,
    BookingOrder,
    BookingOrderItem,
    BookingStatus,
    Message,
    MessageChannel,
    MessageType,
    ServiceItem,
    Timeslot,
    User,
    UserRole,
    Venue,
    VenuePlayer,
    VenuePlayerStatus,
    VenueProfile,
    CancellationRequestStatus,
)
from app.schemas import (
    BookingAndOrderRead,
    BookingCreate,
    BookingOrderItemRead,
    BookingOrderRead,
    BookingRead,
    BookingWithOrderCreate,
    CancellationRequestCreate,
    CancellationRequestRead,
    CancellationRequestReview,
    OrderHistoryRow,
)
from app.services.action_audit import log_action
from app.services.booking_engine import cooldown_expiry, update_timeslot_if_full

router = APIRouter(tags=["orders"])


def _build_order_read(order: BookingOrder, items: list[BookingOrderItem]) -> BookingOrderRead:
    return BookingOrderRead(
        id=order.id,
        booking_id=order.booking_id,
        venue_id=order.venue_id,
        player_id=order.player_id,
        total_cost=float(order.total_cost),
        created_at=order.created_at,
        updated_at=order.updated_at,
        items=[
            BookingOrderItemRead(
                id=i.id,
                service_item_id=i.service_item_id,
                service_name_snapshot=i.service_name_snapshot,
                unit_cost_snapshot=float(i.unit_cost_snapshot),
                quantity=i.quantity,
                line_total=float(i.line_total),
            )
            for i in items
        ],
    )


def _build_booking_read(booking: Booking) -> BookingRead:
    return BookingRead(
        id=booking.id,
        timeslot_id=booking.timeslot_id,
        player_id=booking.player_id,
        status=booking.status,
        booked_at=booking.booked_at,
        cooldown_expires=booking.cooldown_expires,
    )


@router.post("/timeslots/{timeslot_id}/book-with-order", response_model=BookingAndOrderRead)
def book_with_order(timeslot_id: str, payload: BookingWithOrderCreate, db: Session = Depends(get_db)) -> BookingAndOrderRead:
    player = db.get(User, payload.player_id)
    if not player or player.role != UserRole.player:
        raise HTTPException(status_code=403, detail="Player role required")

    timeslot = db.get(Timeslot, timeslot_id)
    if not timeslot:
        raise HTTPException(status_code=404, detail="Timeslot not found")

    venue = db.get(Venue, timeslot.venue_id)
    profile = db.scalar(select(VenueProfile).where(VenueProfile.venue_id == venue.id))
    if not profile or not profile.business_whatsapp:
        raise HTTPException(status_code=400, detail="Business owner WhatsApp must be configured before booking")

    membership = db.scalar(
        select(VenuePlayer).where(
            VenuePlayer.venue_id == timeslot.venue_id,
            VenuePlayer.player_id == payload.player_id,
            VenuePlayer.status == VenuePlayerStatus.approved,
        )
    )
    if not membership:
        raise HTTPException(status_code=403, detail="Player not approved for this venue")

    active_count = db.scalar(
        select(func.count(Booking.id)).where(
            Booking.timeslot_id == timeslot_id,
            Booking.status != BookingStatus.cancelled,
        )
    )
    if active_count and active_count >= 4:
        raise HTTPException(status_code=409, detail="Timeslot is full")

    existing = db.scalar(select(Booking).where(Booking.timeslot_id == timeslot_id, Booking.player_id == payload.player_id))
    existing_status = existing.status.value if existing is not None and hasattr(existing.status, "value") else (str(existing.status) if existing else None)
    if existing and existing_status != BookingStatus.cancelled.value:
        raise HTTPException(status_code=409, detail="Player already booked this timeslot")

    if existing and existing_status == BookingStatus.cancelled.value:
        booking = existing
        booking.status = BookingStatus.cooling_down
        booking.cooldown_expires = cooldown_expiry(venue.cooldown_minutes)
        booking.cancelled_by = None
        booking.cancelled_at = None
        booking.locked_at = None
        db.flush()
    else:
        booking = Booking(
            timeslot_id=timeslot_id,
            player_id=payload.player_id,
            status=BookingStatus.cooling_down,
            cooldown_expires=cooldown_expiry(venue.cooldown_minutes),
        )
        db.add(booking)
        db.flush()

    order = db.scalar(select(BookingOrder).where(BookingOrder.booking_id == booking.id))
    if not order:
        order = BookingOrder(booking_id=booking.id, venue_id=venue.id, player_id=payload.player_id, total_cost=0)
        db.add(order)
        db.flush()
    else:
        previous_items = db.execute(select(BookingOrderItem).where(BookingOrderItem.order_id == order.id)).scalars().all()
        for prev in previous_items:
            db.delete(prev)
        order.total_cost = 0
        order.updated_at = datetime.utcnow()

    total = 0.0
    items: list[BookingOrderItem] = []
    for req in payload.order_items:
        service = db.get(ServiceItem, req.service_item_id)
        if not service or service.venue_id != venue.id or not service.is_active:
            raise HTTPException(status_code=400, detail="Invalid service item in order")
        line_total = float(service.cost) * req.quantity
        total += line_total
        item = BookingOrderItem(
            order_id=order.id,
            service_item_id=service.id,
            service_name_snapshot=service.name,
            unit_cost_snapshot=service.cost,
            quantity=req.quantity,
            line_total=line_total,
        )
        db.add(item)
        items.append(item)

    order.total_cost = total

    msg = Message(
        venue_id=venue.id,
        sent_by=payload.player_id,
        message_type=MessageType.broadcast,
        content=(
            f"New booking request: {player.name} for {timeslot.date} {timeslot.start_time} table {timeslot.table_number}. "
            f"Order total {profile.currency_code} {total:.2f}. Please confirm."
        ),
        recipient_count=1,
        channel=MessageChannel.whatsapp_link,
    )
    db.add(msg)

    update_timeslot_if_full(db, timeslot_id, payload.player_id)
    log_action(
        db,
        actor_id=payload.player_id,
        action_type="booking_with_order.created",
        venue_id=venue.id,
        target_type="booking",
        target_id=booking.id,
        metadata={"order_total": total, "items": len(payload.order_items)},
    )

    db.commit()
    db.refresh(booking)
    db.refresh(order)

    order_items = db.execute(select(BookingOrderItem).where(BookingOrderItem.order_id == order.id)).scalars().all()
    return BookingAndOrderRead(booking=_build_booking_read(booking), order=_build_order_read(order, order_items))


@router.put("/bookings/{booking_id}/order", response_model=BookingOrderRead)
def update_order_items(booking_id: str, payload: BookingWithOrderCreate, db: Session = Depends(get_db)) -> BookingOrderRead:
    booking = db.get(Booking, booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    if booking.player_id != payload.player_id:
        raise HTTPException(status_code=403, detail="Only booking owner can edit order")
    if datetime.utcnow() > booking.cooldown_expires:
        raise HTTPException(status_code=409, detail="Cooldown expired. Order edit requires business owner assistance")

    timeslot = db.get(Timeslot, booking.timeslot_id)
    venue = db.get(Venue, timeslot.venue_id)

    order = db.scalar(select(BookingOrder).where(BookingOrder.booking_id == booking_id))
    if not order:
        order = BookingOrder(booking_id=booking.id, venue_id=venue.id, player_id=booking.player_id, total_cost=0)
        db.add(order)
        db.flush()

    db.execute(select(BookingOrderItem).where(BookingOrderItem.order_id == order.id)).scalars().all()
    existing_items = db.execute(select(BookingOrderItem).where(BookingOrderItem.order_id == order.id)).scalars().all()
    for i in existing_items:
        db.delete(i)

    total = 0.0
    for req in payload.order_items:
        service = db.get(ServiceItem, req.service_item_id)
        if not service or service.venue_id != venue.id or not service.is_active:
            raise HTTPException(status_code=400, detail="Invalid service item in order")
        line_total = float(service.cost) * req.quantity
        total += line_total
        db.add(
            BookingOrderItem(
                order_id=order.id,
                service_item_id=service.id,
                service_name_snapshot=service.name,
                unit_cost_snapshot=service.cost,
                quantity=req.quantity,
                line_total=line_total,
            )
        )

    order.total_cost = total
    order.updated_at = datetime.utcnow()

    log_action(
        db,
        actor_id=payload.player_id,
        action_type="order.updated",
        venue_id=venue.id,
        target_type="order",
        target_id=order.id,
        metadata={"order_total": total, "items": len(payload.order_items)},
    )

    db.commit()
    db.refresh(order)
    items = db.execute(select(BookingOrderItem).where(BookingOrderItem.order_id == order.id)).scalars().all()
    return _build_order_read(order, items)


@router.post("/bookings/{booking_id}/cancellation-request", response_model=CancellationRequestRead)
def request_booking_cancellation(booking_id: str, payload: CancellationRequestCreate, db: Session = Depends(get_db)) -> CancellationRequestRead:
    booking = db.get(Booking, booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    if booking.player_id != payload.actor_id:
        raise HTTPException(status_code=403, detail="Only booking owner can request cancellation")
    if datetime.utcnow() <= booking.cooldown_expires:
        raise HTTPException(status_code=409, detail="Cooldown still active. Use direct cancel instead")

    timeslot = db.get(Timeslot, booking.timeslot_id)
    venue = db.get(Venue, timeslot.venue_id)
    profile = db.scalar(select(VenueProfile).where(VenueProfile.venue_id == venue.id))
    if not profile or not profile.business_whatsapp:
        raise HTTPException(status_code=400, detail="Business owner WhatsApp must be configured before cancellation requests")

    req = BookingCancellationRequest(
        booking_id=booking.id,
        venue_id=venue.id,
        requested_by=payload.actor_id,
        reason=payload.reason,
        status=CancellationRequestStatus.pending,
    )
    db.add(req)
    db.flush()

    db.add(
        Message(
            venue_id=venue.id,
            sent_by=payload.actor_id,
            message_type=MessageType.broadcast,
            content=(
                f"Cancellation request pending for booking {booking.id} at {timeslot.date} {timeslot.start_time}. "
                f"Reason: {payload.reason or 'N/A'}"
            ),
            recipient_count=1,
            channel=MessageChannel.whatsapp_link,
        )
    )

    log_action(
        db,
        actor_id=payload.actor_id,
        action_type="booking.cancellation_requested",
        venue_id=venue.id,
        target_type="cancellation_request",
        target_id=req.id,
        metadata={"reason": payload.reason},
    )

    db.commit()
    db.refresh(req)
    return CancellationRequestRead(
        id=req.id,
        booking_id=req.booking_id,
        venue_id=req.venue_id,
        requested_by=req.requested_by,
        status=req.status,
        reason=req.reason,
        reviewed_by=req.reviewed_by,
        reviewed_at=req.reviewed_at,
        created_at=req.created_at,
    )


@router.patch("/cancellation-requests/{request_id}", response_model=CancellationRequestRead)
def review_cancellation_request(request_id: str, payload: CancellationRequestReview, db: Session = Depends(get_db)) -> CancellationRequestRead:
    req = db.get(BookingCancellationRequest, request_id)
    if not req:
        raise HTTPException(status_code=404, detail="Cancellation request not found")

    reviewer = db.get(User, payload.reviewer_id)
    if not reviewer or reviewer.role not in (UserRole.business_owner, UserRole.platform_owner):
        raise HTTPException(status_code=403, detail="Business/admin role required")

    venue = db.get(Venue, req.venue_id)
    if reviewer.role == UserRole.business_owner and venue.owner_id != reviewer.id:
        raise HTTPException(status_code=403, detail="Business owner does not own this venue")

    req.status = CancellationRequestStatus.approved if payload.approve else CancellationRequestStatus.rejected
    req.reviewed_by = payload.reviewer_id
    req.reviewed_at = datetime.utcnow()

    if payload.approve:
        booking = db.get(Booking, req.booking_id)
        if booking and booking.status != BookingStatus.cancelled:
            booking.status = BookingStatus.cancelled
            booking.cancelled_by = payload.reviewer_id
            booking.cancelled_at = datetime.utcnow()

    log_action(
        db,
        actor_id=payload.reviewer_id,
        action_type="booking.cancellation_reviewed",
        venue_id=req.venue_id,
        target_type="cancellation_request",
        target_id=req.id,
        metadata={"approved": payload.approve},
    )
    db.commit()
    db.refresh(req)

    return CancellationRequestRead(
        id=req.id,
        booking_id=req.booking_id,
        venue_id=req.venue_id,
        requested_by=req.requested_by,
        status=req.status,
        reason=req.reason,
        reviewed_by=req.reviewed_by,
        reviewed_at=req.reviewed_at,
        created_at=req.created_at,
    )


@router.get("/venues/{venue_id}/order-history", response_model=list[OrderHistoryRow])
def get_order_history(
    venue_id: str,
    business_owner_id: str,
    search: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    db: Session = Depends(get_db),
) -> list[OrderHistoryRow]:
    venue = db.get(Venue, venue_id)
    if not venue:
        raise HTTPException(status_code=404, detail="Venue not found")

    owner = db.get(User, business_owner_id)
    if not owner or owner.role not in (UserRole.business_owner, UserRole.platform_owner):
        raise HTTPException(status_code=403, detail="Business/admin role required")
    if owner.role == UserRole.business_owner and venue.owner_id != owner.id:
        raise HTTPException(status_code=403, detail="Business owner does not own this venue")

    stmt = (
        select(BookingOrder, Booking, User)
        .join(Booking, Booking.id == BookingOrder.booking_id)
        .join(User, User.id == Booking.player_id)
        .where(BookingOrder.venue_id == venue_id)
        .order_by(BookingOrder.created_at.desc())
    )

    if search:
        pattern = f"%{search.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(User.name).like(pattern),
                func.lower(User.phone).like(pattern),
            )
        )

    if from_date:
        stmt = stmt.where(func.date(BookingOrder.created_at) >= from_date)
    if to_date:
        stmt = stmt.where(func.date(BookingOrder.created_at) <= to_date)

    rows = db.execute(stmt).all()
    out: list[OrderHistoryRow] = []
    for order, booking, player in rows:
        items = db.execute(select(BookingOrderItem).where(BookingOrderItem.order_id == order.id)).scalars().all()
        summary = ", ".join([f"{i.service_name_snapshot} x{i.quantity}" for i in items])
        out.append(
            OrderHistoryRow(
                order_id=order.id,
                booking_id=booking.id,
                player_id=player.id,
                player_name=player.name,
                player_phone=player.phone,
                total_cost=float(order.total_cost),
                booking_status=booking.status,
                booking_time=booking.booked_at,
                created_at=order.created_at,
                items_summary=summary,
            )
        )
    return out
