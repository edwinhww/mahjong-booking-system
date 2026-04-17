from datetime import datetime
from pathlib import Path
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ServiceItem, User, UserRole, Venue, VenueProfile
from app.schemas import (
    ServiceItemCreate,
    ServiceItemRead,
    ServiceItemUpdate,
    VenueProfileRead,
    VenueProfileUpsert,
)
from app.services.action_audit import log_action

router = APIRouter(prefix="/venues", tags=["catalog"])

UPLOADS_DIR = Path(__file__).resolve().parents[2] / "uploads" / "services"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


def _require_venue_admin(db: Session, venue: Venue, admin_id: str) -> User:
    admin = db.get(User, admin_id)
    if not admin:
        raise HTTPException(status_code=404, detail="Admin user not found")
    if admin.role not in (UserRole.business_owner, UserRole.platform_owner):
        raise HTTPException(status_code=403, detail="Admin role required")
    if admin.role == UserRole.business_owner and venue.owner_id != admin.id:
        raise HTTPException(status_code=403, detail="Admin does not own this venue")
    return admin


@router.post("/uploads/service-image")
def upload_service_image(file: UploadFile = File(...)) -> dict[str, str]:
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Only image uploads are allowed")

    ext = Path(file.filename or "").suffix.lower() or ".jpg"
    if ext not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        raise HTTPException(status_code=400, detail="Unsupported image extension")

    name = f"service_{uuid.uuid4().hex}{ext}"
    target = UPLOADS_DIR / name
    with target.open("wb") as f:
        f.write(file.file.read())

    return {"image_url": f"/uploads/services/{name}"}


@router.get("/{venue_id}/profile", response_model=VenueProfileRead)
def get_venue_profile(venue_id: str, db: Session = Depends(get_db)) -> VenueProfileRead:
    venue = db.get(Venue, venue_id)
    if not venue:
        raise HTTPException(status_code=404, detail="Venue not found")

    profile = db.scalar(select(VenueProfile).where(VenueProfile.venue_id == venue_id))
    if not profile:
        profile = VenueProfile(venue_id=venue_id, currency_code="GBP", business_whatsapp="")
        db.add(profile)
        db.commit()
        db.refresh(profile)

    return VenueProfileRead(
        id=profile.id,
        venue_id=profile.venue_id,
        currency_code=profile.currency_code,
        business_whatsapp=profile.business_whatsapp,
        updated_at=profile.updated_at,
    )


@router.put("/{venue_id}/profile", response_model=VenueProfileRead)
def upsert_venue_profile(venue_id: str, payload: VenueProfileUpsert, admin_id: str, db: Session = Depends(get_db)) -> VenueProfileRead:
    venue = db.get(Venue, venue_id)
    if not venue:
        raise HTTPException(status_code=404, detail="Venue not found")

    _require_venue_admin(db, venue, admin_id)

    profile = db.scalar(select(VenueProfile).where(VenueProfile.venue_id == venue_id))
    if not profile:
        profile = VenueProfile(venue_id=venue_id, currency_code=payload.currency_code.upper(), business_whatsapp=payload.business_whatsapp)
        db.add(profile)
    else:
        profile.currency_code = payload.currency_code.upper()
        profile.business_whatsapp = payload.business_whatsapp
        profile.updated_at = datetime.utcnow()

    log_action(
        db,
        actor_id=admin_id,
        action_type="venue.profile.updated",
        venue_id=venue_id,
        target_type="venue_profile",
        target_id=profile.id,
        metadata={"currency_code": profile.currency_code},
    )
    db.commit()
    db.refresh(profile)

    return VenueProfileRead(
        id=profile.id,
        venue_id=profile.venue_id,
        currency_code=profile.currency_code,
        business_whatsapp=profile.business_whatsapp,
        updated_at=profile.updated_at,
    )


@router.post("/{venue_id}/services", response_model=ServiceItemRead)
def create_service_item(venue_id: str, payload: ServiceItemCreate, admin_id: str, db: Session = Depends(get_db)) -> ServiceItemRead:
    venue = db.get(Venue, venue_id)
    if not venue:
        raise HTTPException(status_code=404, detail="Venue not found")

    _require_venue_admin(db, venue, admin_id)

    item = ServiceItem(
        venue_id=venue_id,
        category=payload.category,
        name=payload.name,
        description=payload.description,
        image_url=payload.image_url,
        cost=payload.cost,
        is_active=payload.is_active,
    )
    db.add(item)

    log_action(
        db,
        actor_id=admin_id,
        action_type="service.created",
        venue_id=venue_id,
        target_type="service_item",
        target_id=item.id,
        metadata={"name": item.name, "cost": float(item.cost)},
    )
    db.commit()
    db.refresh(item)

    return ServiceItemRead(
        id=item.id,
        venue_id=item.venue_id,
        category=item.category,
        name=item.name,
        description=item.description,
        image_url=item.image_url,
        cost=float(item.cost),
        is_active=item.is_active,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


@router.get("/{venue_id}/services", response_model=list[ServiceItemRead])
def list_service_items(venue_id: str, active_only: bool = False, db: Session = Depends(get_db)) -> list[ServiceItemRead]:
    venue = db.get(Venue, venue_id)
    if not venue:
        raise HTTPException(status_code=404, detail="Venue not found")

    stmt = select(ServiceItem).where(ServiceItem.venue_id == venue_id)
    if active_only:
        stmt = stmt.where(ServiceItem.is_active.is_(True))

    items = db.execute(stmt.order_by(ServiceItem.created_at.desc())).scalars().all()
    return [
        ServiceItemRead(
            id=item.id,
            venue_id=item.venue_id,
            category=item.category,
            name=item.name,
            description=item.description,
            image_url=item.image_url,
            cost=float(item.cost),
            is_active=item.is_active,
            created_at=item.created_at,
            updated_at=item.updated_at,
        )
        for item in items
    ]


@router.patch("/{venue_id}/services/{service_id}", response_model=ServiceItemRead)
def update_service_item(
    venue_id: str,
    service_id: str,
    payload: ServiceItemUpdate,
    admin_id: str,
    db: Session = Depends(get_db),
) -> ServiceItemRead:
    venue = db.get(Venue, venue_id)
    if not venue:
        raise HTTPException(status_code=404, detail="Venue not found")

    _require_venue_admin(db, venue, admin_id)

    item = db.get(ServiceItem, service_id)
    if not item or item.venue_id != venue_id:
        raise HTTPException(status_code=404, detail="Service item not found")

    for k, v in payload.model_dump(exclude_none=True).items():
        setattr(item, k, v)
    item.updated_at = datetime.utcnow()

    log_action(
        db,
        actor_id=admin_id,
        action_type="service.updated",
        venue_id=venue_id,
        target_type="service_item",
        target_id=item.id,
        metadata={"name": item.name, "is_active": item.is_active},
    )
    db.commit()
    db.refresh(item)

    return ServiceItemRead(
        id=item.id,
        venue_id=item.venue_id,
        category=item.category,
        name=item.name,
        description=item.description,
        image_url=item.image_url,
        cost=float(item.cost),
        is_active=item.is_active,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


@router.delete("/{venue_id}/services/{service_id}")
def delete_service_item(venue_id: str, service_id: str, admin_id: str, db: Session = Depends(get_db)) -> dict[str, bool]:
    venue = db.get(Venue, venue_id)
    if not venue:
        raise HTTPException(status_code=404, detail="Venue not found")

    _require_venue_admin(db, venue, admin_id)

    item = db.get(ServiceItem, service_id)
    if not item or item.venue_id != venue_id:
        raise HTTPException(status_code=404, detail="Service item not found")

    log_action(
        db,
        actor_id=admin_id,
        action_type="service.deleted",
        venue_id=venue_id,
        target_type="service_item",
        target_id=item.id,
        metadata={"name": item.name},
    )
    db.delete(item)
    db.commit()
    return {"deleted": True}
