from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AuditActionType, AuditLog, Booking, BookingStatus, Timeslot, User, UserRole, Venue, VenuePlayer, VenuePlayerStatus
from app.schemas import BookingCreate, BookingRead, VenueBookingRead
from app.services.action_audit import log_action
from app.services.booking_engine import cooldown_expiry, update_timeslot_if_full

router = APIRouter(tags=["bookings"])


@router.post("/timeslots/{timeslot_id}/book", response_model=BookingRead)
def create_booking(timeslot_id: str, payload: BookingCreate, db: Session = Depends(get_db)) -> BookingRead:
    player = db.get(User, payload.player_id)
    if not player or player.role != UserRole.player:
        raise HTTPException(status_code=403, detail="Player role required")

    timeslot = db.get(Timeslot, timeslot_id)
    if not timeslot:
        raise HTTPException(status_code=404, detail="Timeslot not found")

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

    venue = db.get(Venue, timeslot.venue_id)
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
    else:
        booking = Booking(
            timeslot_id=timeslot_id,
            player_id=payload.player_id,
            status=BookingStatus.cooling_down,
            cooldown_expires=cooldown_expiry(venue.cooldown_minutes),
        )
        db.add(booking)
    db.commit()
    db.refresh(booking)

    update_timeslot_if_full(db, timeslot_id, payload.player_id)
    log_action(
        db,
        actor_id=payload.player_id,
        action_type="booking.created",
        venue_id=timeslot.venue_id,
        target_type="booking",
        target_id=booking.id,
        metadata={"timeslot_id": timeslot_id},
    )
    db.commit()

    return BookingRead(
        id=booking.id,
        timeslot_id=booking.timeslot_id,
        player_id=booking.player_id,
        status=booking.status,
        booked_at=booking.booked_at,
        cooldown_expires=booking.cooldown_expires,
    )


@router.delete("/bookings/{booking_id}", response_model=BookingRead)
def cancel_booking(booking_id: str, actor_id: str, db: Session = Depends(get_db)) -> BookingRead:
    actor = db.get(User, actor_id)
    if not actor:
        raise HTTPException(status_code=404, detail="Actor not found")

    booking = db.get(Booking, booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    if booking.player_id != actor_id:
        raise HTTPException(status_code=403, detail="Only the booking owner can cancel")
    if datetime.utcnow() > booking.cooldown_expires:
        raise HTTPException(status_code=409, detail="Cooldown expired. Please submit a cancellation request to the business owner")

    booking.status = BookingStatus.cancelled
    booking.cancelled_by = actor_id
    booking.cancelled_at = datetime.utcnow()
    log_action(
        db,
        actor_id=actor_id,
        action_type="booking.cancelled",
        target_type="booking",
        target_id=booking.id,
        metadata={"source": "direct_cancel"},
    )
    db.commit()
    db.refresh(booking)

    return BookingRead(
        id=booking.id,
        timeslot_id=booking.timeslot_id,
        player_id=booking.player_id,
        status=booking.status,
        booked_at=booking.booked_at,
        cooldown_expires=booking.cooldown_expires,
    )


@router.patch("/bookings/{booking_id}/unlock", response_model=BookingRead)
def unlock_booking(booking_id: str, admin_id: str, db: Session = Depends(get_db)) -> BookingRead:
    admin = db.get(User, admin_id)
    if not admin:
        raise HTTPException(status_code=404, detail="Admin user not found")
    if admin.role not in (UserRole.business_owner, UserRole.platform_owner):
        raise HTTPException(status_code=403, detail="Admin role required")

    booking = db.get(Booking, booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    if booking.status == BookingStatus.cancelled:
        raise HTTPException(status_code=409, detail="Booking already cancelled")

    booking.status = BookingStatus.cancelled
    booking.cancelled_by = admin_id
    booking.cancelled_at = datetime.utcnow()

    timeslot = db.get(Timeslot, booking.timeslot_id)
    venue = db.get(Venue, timeslot.venue_id)
    if admin.role == UserRole.business_owner and venue.owner_id != admin.id:
        raise HTTPException(status_code=403, detail="Admin does not own this venue")

    db.add(
        AuditLog(
            venue_id=timeslot.venue_id,
            action_type=AuditActionType.player_unlocked,
            reference_id=booking.id,
            performed_by=admin_id,
        )
    )
    log_action(
        db,
        actor_id=admin_id,
        action_type="booking.unlocked",
        venue_id=timeslot.venue_id,
        target_type="booking",
        target_id=booking.id,
        metadata={"source": "business_admin_unlock"},
    )
    db.commit()
    db.refresh(booking)

    return BookingRead(
        id=booking.id,
        timeslot_id=booking.timeslot_id,
        player_id=booking.player_id,
        status=booking.status,
        booked_at=booking.booked_at,
        cooldown_expires=booking.cooldown_expires,
    )


@router.get("/venues/{venue_id}/bookings", response_model=list[VenueBookingRead])
def list_venue_bookings(venue_id: str, day: date | None = None, db: Session = Depends(get_db)) -> list[VenueBookingRead]:
    venue = db.get(Venue, venue_id)
    if not venue:
        raise HTTPException(status_code=404, detail="Venue not found")

    stmt = (
        select(Booking, Timeslot)
        .join(Timeslot, Timeslot.id == Booking.timeslot_id)
        .where(Timeslot.venue_id == venue_id)
        .order_by(Timeslot.start_time, Timeslot.table_number)
    )
    if day is not None:
        stmt = stmt.where(Timeslot.date == day)

    rows = db.execute(stmt).all()
    return [
        VenueBookingRead(
            id=b.id,
            timeslot_id=b.timeslot_id,
            player_id=b.player_id,
            status=b.status,
            booked_at=b.booked_at,
            cooldown_expires=b.cooldown_expires,
            table_number=t.table_number,
            start_time=t.start_time,
            end_time=t.end_time,
        )
        for b, t in rows
    ]
