from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    AuditActionType,
    AuditLog,
    Booking,
    BookingStatus,
    Message,
    MessageChannel,
    MessageType,
    Timeslot,
    User,
    UserRole,
    Venue,
    VenuePlayer,
    VenuePlayerStatus,
)
from app.schemas import VenueCreate, VenueJoinRequest, VenuePlayerDetailRead, VenuePlayerRead, VenueRead, VenueUpdate, VenueUpdateResponse
from app.services.action_audit import log_action

router = APIRouter(prefix="/venues", tags=["venues"])


def _require_venue_admin(db: Session, venue: Venue, admin_id: str) -> User:
    admin = db.get(User, admin_id)
    if not admin:
        raise HTTPException(status_code=404, detail="Admin user not found")
    if admin.role not in (UserRole.business_owner, UserRole.platform_owner):
        raise HTTPException(status_code=403, detail="Admin role required")
    if admin.role == UserRole.business_owner and venue.owner_id != admin.id:
        raise HTTPException(status_code=403, detail="Admin does not own this venue")
    return admin


def _reallocate_dropped_table_bookings(db: Session, venue: Venue, new_table_count: int, admin_id: str) -> int:
    if new_table_count >= venue.table_count:
        return 0

    timeslots = db.execute(select(Timeslot).where(Timeslot.venue_id == venue.id)).scalars().all()
    if not timeslots:
        return 0

    retained_slots = [slot for slot in timeslots if slot.table_number <= new_table_count]
    dropped_slots = [slot for slot in timeslots if slot.table_number > new_table_count]
    if not dropped_slots:
        return 0

    slot_by_id = {slot.id: slot for slot in timeslots}
    retained_slots_sorted = sorted(retained_slots, key=lambda slot: (slot.date, slot.start_time, slot.end_time, slot.table_number))
    target_groups: dict[tuple, list[Timeslot]] = {}
    for slot in retained_slots:
        key = (slot.date, slot.start_time, slot.end_time)
        target_groups.setdefault(key, []).append(slot)
    for group in target_groups.values():
        group.sort(key=lambda slot: slot.table_number)

    active_bookings = db.execute(
        select(Booking, User)
        .join(Timeslot, Timeslot.id == Booking.timeslot_id)
        .join(User, User.id == Booking.player_id)
        .where(
            Timeslot.venue_id == venue.id,
            Booking.status != BookingStatus.cancelled,
        )
        .order_by(Timeslot.date.asc(), Timeslot.start_time.asc(), Booking.booked_at.asc())
    ).all()

    occupancy = {slot.id: 0 for slot in retained_slots}
    players_in_slot: dict[str, set[str]] = {slot.id: set() for slot in retained_slots}
    dropped_booking_rows: list[tuple[Booking, User]] = []
    for booking, player in active_bookings:
        slot = slot_by_id.get(booking.timeslot_id)
        if not slot:
            continue
        if slot.table_number <= new_table_count:
            if slot.id in occupancy:
                occupancy[slot.id] += 1
                players_in_slot[slot.id].add(booking.player_id)
        else:
            dropped_booking_rows.append((booking, player))

    moved_count = 0
    for booking, player in dropped_booking_rows:
        source_slot = slot_by_id.get(booking.timeslot_id)
        if not source_slot:
            continue

        target_slot = None
        key = (source_slot.date, source_slot.start_time, source_slot.end_time)
        candidate_slots = target_groups.get(key, [])
        if candidate_slots:
            candidate_slots = sorted(candidate_slots, key=lambda slot: (occupancy.get(slot.id, 0), slot.table_number))
            target_slot = next(
                (
                    slot
                    for slot in candidate_slots
                    if occupancy.get(slot.id, 0) < 4 and booking.player_id not in players_in_slot.get(slot.id, set())
                ),
                None,
            )

        # If the same timeslot is full, move to the next available slot in chronological order.
        if not target_slot:
            source_rank = (source_slot.date, source_slot.start_time, source_slot.end_time, source_slot.table_number)
            later_slots = [slot for slot in retained_slots_sorted if (slot.date, slot.start_time, slot.end_time, slot.table_number) > source_rank]
            target_slot = next(
                (
                    slot
                    for slot in later_slots
                    if occupancy.get(slot.id, 0) < 4 and booking.player_id not in players_in_slot.get(slot.id, set())
                ),
                None,
            )

        if not target_slot:
            raise HTTPException(
                status_code=409,
                detail="Cannot reduce concurrent games: no later slots available with capacity for all affected players",
            )

        booking.timeslot_id = target_slot.id
        occupancy[target_slot.id] = occupancy.get(target_slot.id, 0) + 1
        players_in_slot[target_slot.id].add(booking.player_id)
        moved_count += 1

        draft_text = (
            f"Draft: Table reassignment for {player.name} ({player.phone}). "
            f"Session {source_slot.date.isoformat()} {source_slot.start_time.strftime('%H:%M')}-{source_slot.end_time.strftime('%H:%M')} "
            f"moved from T{source_slot.table_number} to {target_slot.date.isoformat()} {target_slot.start_time.strftime('%H:%M')}-{target_slot.end_time.strftime('%H:%M')} T{target_slot.table_number}. "
            f"Please send WhatsApp confirmation to the player."
        )
        db.add(
            Message(
                venue_id=venue.id,
                sent_by=admin_id,
                message_type=MessageType.reminder,
                content=draft_text,
                recipient_count=1,
                channel=MessageChannel.in_app,
            )
        )

    return moved_count


@router.get("", response_model=list[VenueRead])
def list_venues(include_inactive: bool = False, player_id: str | None = None, db: Session = Depends(get_db)) -> list[VenueRead]:
    stmt = select(Venue)
    if not include_inactive:
        stmt = stmt.where(Venue.status == "active")
    if player_id:
        stmt = (
            stmt.join(VenuePlayer, VenuePlayer.venue_id == Venue.id)
            .where(
                VenuePlayer.player_id == player_id,
                VenuePlayer.status == VenuePlayerStatus.approved,
            )
        )
    venues = db.execute(stmt).scalars().all()
    return [
        VenueRead(
            id=v.id,
            owner_id=v.owner_id,
            name=v.name,
            opening_time=v.opening_time,
            closing_time=v.closing_time,
            table_count=v.table_count,
            session_duration_hrs=v.session_duration_hrs,
            cooldown_minutes=v.cooldown_minutes,
            session_fee=float(v.session_fee),
            platform_fee_pct=float(v.platform_fee_pct),
            status=v.status,
        )
        for v in venues
    ]


@router.post("", response_model=VenueRead)
def create_venue(payload: VenueCreate, db: Session = Depends(get_db)) -> VenueRead:
    owner = db.get(User, payload.owner_id)
    if not owner or owner.role != UserRole.business_owner:
        raise HTTPException(status_code=400, detail="owner_id must be a business owner")

    venue = Venue(**payload.model_dump())
    db.add(venue)
    db.flush()
    log_action(
        db,
        actor_id=payload.owner_id,
        action_type="venue.created",
        venue_id=venue.id,
        target_type="venue",
        target_id=venue.id,
        metadata={"name": venue.name},
    )
    db.commit()
    db.refresh(venue)

    return VenueRead(
        id=venue.id,
        owner_id=venue.owner_id,
        name=venue.name,
        opening_time=venue.opening_time,
        closing_time=venue.closing_time,
        table_count=venue.table_count,
        session_duration_hrs=venue.session_duration_hrs,
        cooldown_minutes=venue.cooldown_minutes,
        session_fee=float(venue.session_fee),
        platform_fee_pct=float(venue.platform_fee_pct),
        status=venue.status,
    )


@router.post("/{venue_id}/join", response_model=VenuePlayerRead)
def join_venue(venue_id: str, payload: VenueJoinRequest, db: Session = Depends(get_db)) -> VenuePlayerRead:
    venue = db.get(Venue, venue_id)
    player = db.get(User, payload.player_id)
    if not venue:
        raise HTTPException(status_code=404, detail="Venue not found")
    if not player or player.role != UserRole.player:
        raise HTTPException(status_code=400, detail="player_id must be a player")

    vp = db.scalar(select(VenuePlayer).where(VenuePlayer.venue_id == venue_id, VenuePlayer.player_id == payload.player_id))
    if not vp:
        vp = VenuePlayer(venue_id=venue_id, player_id=payload.player_id, status=VenuePlayerStatus.pending)
        db.add(vp)
        db.flush()
        log_action(
            db,
            actor_id=payload.player_id,
            action_type="venue.join_requested",
            venue_id=venue_id,
            target_type="venue_player",
            target_id=vp.id,
            metadata={"status": vp.status.value},
        )
        db.commit()
        db.refresh(vp)

    return VenuePlayerRead(id=vp.id, venue_id=vp.venue_id, player_id=vp.player_id, status=vp.status, created_at=vp.created_at)


@router.patch("/{venue_id}/players/{player_id}/approve", response_model=VenuePlayerRead)
def approve_player(venue_id: str, player_id: str, approver_id: str, db: Session = Depends(get_db)) -> VenuePlayerRead:
    venue = db.get(Venue, venue_id)
    if not venue:
        raise HTTPException(status_code=404, detail="Venue not found")
    _require_venue_admin(db, venue, approver_id)

    vp = db.scalar(select(VenuePlayer).where(VenuePlayer.venue_id == venue_id, VenuePlayer.player_id == player_id))
    if not vp:
        raise HTTPException(status_code=404, detail="Venue-player membership not found")

    vp.status = VenuePlayerStatus.approved
    vp.approved_by = approver_id
    vp.approved_at = datetime.utcnow()
    db.add(
        AuditLog(
            venue_id=venue_id,
            action_type=AuditActionType.player_approved,
            reference_id=vp.id,
            performed_by=approver_id,
        )
    )
    log_action(
        db,
        actor_id=approver_id,
        action_type="venue.player_approved",
        venue_id=venue_id,
        target_type="venue_player",
        target_id=vp.id,
        metadata={"player_id": player_id},
    )
    db.commit()

    return VenuePlayerRead(id=vp.id, venue_id=vp.venue_id, player_id=vp.player_id, status=vp.status, created_at=vp.created_at)


@router.get("/{venue_id}/players", response_model=list[VenuePlayerDetailRead])
def list_venue_players(venue_id: str, status: VenuePlayerStatus | None = None, db: Session = Depends(get_db)) -> list[VenuePlayerDetailRead]:
    venue = db.get(Venue, venue_id)
    if not venue:
        raise HTTPException(status_code=404, detail="Venue not found")

    stmt = select(VenuePlayer, User).join(User, User.id == VenuePlayer.player_id).where(VenuePlayer.venue_id == venue_id)
    if status is not None:
        stmt = stmt.where(VenuePlayer.status == status)

    rows = db.execute(stmt.order_by(VenuePlayer.created_at.desc())).all()
    return [
        VenuePlayerDetailRead(
            id=vp.id,
            player_id=vp.player_id,
            player_name=u.name,
            player_phone=u.phone,
            status=vp.status,
            created_at=vp.created_at,
        )
        for vp, u in rows
    ]


@router.patch("/{venue_id}", response_model=VenueRead)
def update_venue_settings(venue_id: str, payload: VenueUpdate, admin_id: str, db: Session = Depends(get_db)) -> VenueUpdateResponse:
    venue = db.get(Venue, venue_id)
    if not venue:
        raise HTTPException(status_code=404, detail="Venue not found")

    _require_venue_admin(db, venue, admin_id)

    update_data = payload.model_dump(exclude_none=True)
    if not update_data:
        return VenueUpdateResponse(
            id=venue.id,
            owner_id=venue.owner_id,
            name=venue.name,
            opening_time=venue.opening_time,
            closing_time=venue.closing_time,
            table_count=venue.table_count,
            session_duration_hrs=venue.session_duration_hrs,
            cooldown_minutes=venue.cooldown_minutes,
            session_fee=float(venue.session_fee),
            platform_fee_pct=float(venue.platform_fee_pct),
            status=venue.status,
            reallocated_count=0,
            draft_count=0,
        )

    old_table_count = venue.table_count

    for field, value in update_data.items():
        setattr(venue, field, value)

    moved_count = 0
    if "table_count" in update_data and update_data["table_count"] < old_table_count:
        moved_count = _reallocate_dropped_table_bookings(db, venue, int(update_data["table_count"]), admin_id)

    db.add(
        AuditLog(
            venue_id=venue_id,
            action_type=AuditActionType.settings_changed,
            reference_id=venue.id,
            performed_by=admin_id,
        )
    )
    log_action(
        db,
        actor_id=admin_id,
        action_type="venue.settings_updated",
        venue_id=venue_id,
        target_type="venue",
        target_id=venue.id,
        metadata={"fields": list(update_data.keys()), "reallocated_bookings": moved_count},
    )
    db.commit()
    db.refresh(venue)

    return VenueUpdateResponse(
        id=venue.id,
        owner_id=venue.owner_id,
        name=venue.name,
        opening_time=venue.opening_time,
        closing_time=venue.closing_time,
        table_count=venue.table_count,
        session_duration_hrs=venue.session_duration_hrs,
        cooldown_minutes=venue.cooldown_minutes,
        session_fee=float(venue.session_fee),
        platform_fee_pct=float(venue.platform_fee_pct),
        status=venue.status,
        reallocated_count=moved_count,
        draft_count=moved_count,
    )
