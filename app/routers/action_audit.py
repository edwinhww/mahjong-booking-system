from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ActionAudit, User, UserRole
from app.schemas import ActionAuditRead

router = APIRouter(prefix="/audit", tags=["action-audit"])


@router.get("", response_model=list[ActionAuditRead])
def list_action_audit(
    actor_role: str | None = None,
    action_type: str | None = None,
    search: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    db: Session = Depends(get_db),
) -> list[ActionAuditRead]:
    stmt = select(ActionAudit).order_by(ActionAudit.created_at.desc())

    if actor_role:
        stmt = stmt.where(ActionAudit.actor_role == actor_role)
    if action_type:
        stmt = stmt.where(ActionAudit.action_type == action_type)
    if search:
        pattern = f"%{search.lower()}%"
        stmt = stmt.where(
            func.lower(ActionAudit.action_type).like(pattern)
            | func.lower(func.coalesce(ActionAudit.target_type, "")).like(pattern)
            | func.lower(func.coalesce(ActionAudit.metadata_json, "")).like(pattern)
        )
    if from_date:
        stmt = stmt.where(func.date(ActionAudit.created_at) >= from_date)
    if to_date:
        stmt = stmt.where(func.date(ActionAudit.created_at) <= to_date)

    rows = db.execute(stmt).scalars().all()
    return [
        ActionAuditRead(
            id=r.id,
            actor_id=r.actor_id,
            actor_role=r.actor_role,
            venue_id=r.venue_id,
            action_type=r.action_type,
            target_type=r.target_type,
            target_id=r.target_id,
            metadata_json=r.metadata_json,
            created_at=r.created_at,
        )
        for r in rows
    ]


@router.get("/roles")
def available_roles(db: Session = Depends(get_db)) -> dict[str, list[str]]:
    roles = [r.value for r in UserRole]
    users = db.execute(select(User.role).distinct()).all()
    seen = sorted({u[0].value for u in users})
    return {"supported_roles": roles, "seen_roles": seen}
