from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Booking, BookingOrder, BookingStatus, Timeslot, User, UserRole, UserStatus, Venue, VenuePlayer, VenuePlayerStatus
from app.schemas import PlayerVenueStatsRead, UserAdminUpdate, UserCreate, UserRead, VenueCreate, VenueRead, VenueUpdate
from app.security import hash_password
from app.services.action_audit import log_action

router = APIRouter(prefix="/management", tags=["management"])


def _require_business_owner(db: Session, actor_id: str) -> User:
    actor = db.get(User, actor_id)
    if not actor or actor.role != UserRole.business_owner:
        raise HTTPException(status_code=403, detail="Business owner role required")
    return actor


def _require_venue_owner(db: Session, venue_id: str, actor_id: str) -> Venue:
    owner = _require_business_owner(db, actor_id)
    venue = db.get(Venue, venue_id)
    if not venue:
        raise HTTPException(status_code=404, detail="Venue not found")
    if venue.owner_id != owner.id:
        raise HTTPException(status_code=403, detail="Business owner does not own this venue")
    return venue


def _require_platform_owner(db: Session, actor_id: str) -> User:
    actor = db.get(User, actor_id)
    if not actor or actor.role != UserRole.platform_owner:
        raise HTTPException(status_code=403, detail="Platform owner role required")
    return actor


@router.post("/venues/{venue_id}/players", response_model=UserRead)
def create_player_for_venue(venue_id: str, payload: UserCreate, business_owner_id: str, auto_approve: bool = True, db: Session = Depends(get_db)) -> UserRead:
    venue = _require_venue_owner(db, venue_id, business_owner_id)
    if payload.role != UserRole.player:
        raise HTTPException(status_code=400, detail="Only player users can be created in this endpoint")

    exists = db.scalar(select(User).where(User.phone == payload.phone))
    if exists:
        raise HTTPException(status_code=409, detail="Phone already registered")

    user = User(
        name=payload.name,
        phone=payload.phone,
        email=payload.email,
        password_hash=hash_password(payload.password),
        role=UserRole.player,
        status=UserStatus.active,
        must_change_password=True,
    )
    db.add(user)
    db.flush()

    vp = VenuePlayer(
        venue_id=venue_id,
        player_id=user.id,
        status=VenuePlayerStatus.approved if auto_approve else VenuePlayerStatus.pending,
        approved_by=business_owner_id if auto_approve else None,
        approved_at=datetime.utcnow() if auto_approve else None,
    )
    db.add(vp)

    log_action(
        db,
        actor_id=business_owner_id,
        action_type="user.created",
        venue_id=venue_id,
        target_type="user",
        target_id=user.id,
        metadata={"phone": user.phone, "auto_approve": auto_approve},
    )
    db.commit()
    db.refresh(user)

    return UserRead(id=user.id, name=user.name, phone=user.phone, role=user.role, status=user.status, must_change_password=user.must_change_password)


@router.get("/venues/{venue_id}/players/{user_id}/stats", response_model=PlayerVenueStatsRead)
def get_player_stats_for_venue(venue_id: str, user_id: str, business_owner_id: str, db: Session = Depends(get_db)) -> PlayerVenueStatsRead:
    venue = _require_venue_owner(db, venue_id, business_owner_id)

    user = db.get(User, user_id)
    if not user or user.role != UserRole.player:
        raise HTTPException(status_code=404, detail="Player not found")

    venue_player = db.scalar(
        select(VenuePlayer).where(
            VenuePlayer.venue_id == venue.id,
            VenuePlayer.player_id == user_id,
        )
    )
    if not venue_player:
        raise HTTPException(status_code=404, detail="Player not registered for this venue")

    booking_rows = db.execute(
        select(Booking, Timeslot)
        .join(Timeslot, Timeslot.id == Booking.timeslot_id)
        .where(
            Timeslot.venue_id == venue_id,
            Booking.player_id == user_id,
            Booking.status != BookingStatus.cancelled,
        )
        .order_by(Timeslot.date.desc(), Timeslot.start_time.desc())
    ).all()

    total_games_played = len(booking_rows)
    total_hours_played = 0.0
    last_game_played_at = None
    for booking, timeslot in booking_rows:
        duration_hours = (datetime.combine(timeslot.date, timeslot.end_time) - datetime.combine(timeslot.date, timeslot.start_time)).total_seconds() / 3600.0
        total_hours_played += max(duration_hours, 0)
        if last_game_played_at is None:
            last_game_played_at = datetime.combine(timeslot.date, timeslot.start_time)

    total_spending = db.scalar(
        select(func.coalesce(func.sum(BookingOrder.total_cost), 0))
        .where(
            BookingOrder.venue_id == venue_id,
            BookingOrder.player_id == user_id,
        )
    )

    return PlayerVenueStatsRead(
        player_id=user_id,
        joined_at=venue_player.created_at,
        last_game_played_at=last_game_played_at,
        total_games_played=total_games_played,
        total_hours_played=round(total_hours_played, 2),
        total_spending=float(total_spending or 0),
    )


@router.patch("/users/{user_id}", response_model=UserRead)
def update_user(user_id: str, payload: UserAdminUpdate, business_owner_id: str, db: Session = Depends(get_db)) -> UserRead:
    owner = _require_business_owner(db, business_owner_id)

    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.role != UserRole.player:
        raise HTTPException(status_code=400, detail="Only player users can be managed here")

    membership = db.execute(
        select(VenuePlayer, Venue)
        .join(Venue, Venue.id == VenuePlayer.venue_id)
        .where(VenuePlayer.player_id == user_id, Venue.owner_id == owner.id)
    ).first()
    if not membership:
        raise HTTPException(status_code=403, detail="Business owner cannot manage this player")

    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(user, field, value)

    log_action(
        db,
        actor_id=business_owner_id,
        action_type="user.updated",
        target_type="user",
        target_id=user.id,
        metadata={"fields": list(payload.model_dump(exclude_none=True).keys())},
    )
    db.commit()
    db.refresh(user)

    return UserRead(id=user.id, name=user.name, phone=user.phone, role=user.role, status=user.status, must_change_password=user.must_change_password)


@router.delete("/users/{user_id}")
def delete_user(user_id: str, business_owner_id: str, db: Session = Depends(get_db)) -> dict[str, bool]:
    owner = _require_business_owner(db, business_owner_id)

    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.role != UserRole.player:
        raise HTTPException(status_code=400, detail="Only player users can be managed here")

    membership = db.execute(
        select(VenuePlayer, Venue)
        .join(Venue, Venue.id == VenuePlayer.venue_id)
        .where(VenuePlayer.player_id == user_id, Venue.owner_id == owner.id)
    ).first()
    if not membership:
        raise HTTPException(status_code=403, detail="Business owner cannot manage this player")

    user.status = UserStatus.suspended
    log_action(
        db,
        actor_id=business_owner_id,
        action_type="user.deleted",
        target_type="user",
        target_id=user.id,
        metadata={"soft_delete": True},
    )
    db.commit()
    return {"deleted": True}


@router.post("/admin/venues", response_model=VenueRead)
def admin_create_venue(payload: VenueCreate, platform_owner_id: str, db: Session = Depends(get_db)) -> VenueRead:
    _require_platform_owner(db, platform_owner_id)

    owner = db.get(User, payload.owner_id)
    if not owner or owner.role != UserRole.business_owner:
        raise HTTPException(status_code=400, detail="owner_id must be a business owner")

    venue = Venue(**payload.model_dump())
    db.add(venue)

    log_action(
        db,
        actor_id=platform_owner_id,
        action_type="venue.created",
        venue_id=venue.id,
        target_type="venue",
        target_id=venue.id,
        metadata={"name": payload.name},
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


@router.patch("/admin/venues/{venue_id}", response_model=VenueRead)
def admin_update_venue(venue_id: str, payload: VenueUpdate, platform_owner_id: str, db: Session = Depends(get_db)) -> VenueRead:
    _require_platform_owner(db, platform_owner_id)

    venue = db.get(Venue, venue_id)
    if not venue:
        raise HTTPException(status_code=404, detail="Venue not found")

    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(venue, field, value)

    log_action(
        db,
        actor_id=platform_owner_id,
        action_type="venue.updated",
        venue_id=venue.id,
        target_type="venue",
        target_id=venue.id,
        metadata={"fields": list(payload.model_dump(exclude_none=True).keys())},
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


@router.delete("/admin/venues/{venue_id}")
def admin_delete_venue(venue_id: str, platform_owner_id: str, db: Session = Depends(get_db)) -> dict[str, bool]:
    _require_platform_owner(db, platform_owner_id)

    venue = db.get(Venue, venue_id)
    if not venue:
        raise HTTPException(status_code=404, detail="Venue not found")

    venue.status = "inactive"
    log_action(
        db,
        actor_id=platform_owner_id,
        action_type="venue.deleted",
        venue_id=venue.id,
        target_type="venue",
        target_id=venue.id,
        metadata={"soft_delete": True},
    )
    db.commit()
    return {"deleted": True}
