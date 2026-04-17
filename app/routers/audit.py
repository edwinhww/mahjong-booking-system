from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AuditLog, Venue
from app.schemas import AuditRead

router = APIRouter(prefix="/venues", tags=["audit"])


@router.get("/{venue_id}/audit", response_model=list[AuditRead])
def get_audit_log(venue_id: str, db: Session = Depends(get_db)) -> list[AuditRead]:
    venue = db.get(Venue, venue_id)
    if not venue:
        raise HTTPException(status_code=404, detail="Venue not found")

    rows = db.execute(select(AuditLog).where(AuditLog.venue_id == venue_id).order_by(AuditLog.created_at.desc())).scalars().all()
    return [
        AuditRead(
            id=a.id,
            venue_id=a.venue_id,
            action_type=a.action_type.value,
            reference_id=a.reference_id,
            session_fee=float(a.session_fee) if a.session_fee is not None else None,
            platform_fee=float(a.platform_fee) if a.platform_fee is not None else None,
            performed_by=a.performed_by,
            created_at=a.created_at,
        )
        for a in rows
    ]
