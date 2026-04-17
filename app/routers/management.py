from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, UserRole, UserStatus, Venue, VenuePlayer, VenuePlayerStatus
from app.schemas import UserAdminUpdate, UserCreate, UserRead, VenueCreate, VenueRead, VenueUpdate
from app.security import hash_password
from app.services.action_audit import log_action

router = APIRouter(prefix="/management", tags=["management"])


def _require_business_owner(db: Session, actor_id: str) -> User:
    actor = db.get(User, actor_id)
    if not actor or actor.role != UserRole.business_owner:
        raise HTTPException(status_code=403, detail="Business owner role required")
    return actor


def _require_platform_owner(db: Session, actor_id: str) -> User:
    actor = db.get(User, actor_id)
    if not actor or actor.role != UserRole.platform_owner:
        raise HTTPException(status_code=403, detail="Platform owner role required")
    return actor


@router.post("/venues/{venue_id}/players", response_model=UserRead)
def create_player_for_venue(venue_id: str, payload: UserCreate, business_owner_id: str, auto_approve: bool = True, db: Session = Depends(get_db)) -> UserRead:
    owner = _require_business_owner(db, business_owner_id)
    venue = db.get(Venue, venue_id)
    if not venue:
        raise HTTPException(status_code=404, detail="Venue not found")
    if venue.owner_id != owner.id:
        raise HTTPException(status_code=403, detail="Business owner does not own this venue")
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

    return UserRead(id=user.id, name=user.name, phone=user.phone, role=user.role, status=user.status)


@router.patch("/users/{user_id}", response_model=UserRead)
def update_user(user_id: str, payload: UserAdminUpdate, business_owner_id: str, db: Session = Depends(get_db)) -> UserRead:
    _require_business_owner(db, business_owner_id)

    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.role != UserRole.player:
        raise HTTPException(status_code=400, detail="Only player users can be managed here")

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

    return UserRead(id=user.id, name=user.name, phone=user.phone, role=user.role, status=user.status)


@router.delete("/users/{user_id}")
def delete_user(user_id: str, business_owner_id: str, db: Session = Depends(get_db)) -> dict[str, bool]:
    _require_business_owner(db, business_owner_id)

    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.role != UserRole.player:
        raise HTTPException(status_code=400, detail="Only player users can be managed here")

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
