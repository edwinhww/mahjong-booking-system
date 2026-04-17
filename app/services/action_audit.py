import json

from sqlalchemy.orm import Session

from app.models import ActionAudit, User


def log_action(
    db: Session,
    actor_id: str,
    action_type: str,
    venue_id: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    metadata: dict | None = None,
) -> None:
    actor = db.get(User, actor_id)
    actor_role = actor.role.value if actor else "unknown"
    row = ActionAudit(
        actor_id=actor_id,
        actor_role=actor_role,
        venue_id=venue_id,
        action_type=action_type,
        target_type=target_type,
        target_id=target_id,
        metadata_json=json.dumps(metadata or {}, ensure_ascii=True),
    )
    db.add(row)
