from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Message, User, UserRole, Venue
from app.schemas import MessageCreate, MessageRead
from app.services.action_audit import log_action

router = APIRouter(prefix="/venues", tags=["messages"])


@router.post("/{venue_id}/messages", response_model=MessageRead)
def send_message(venue_id: str, payload: MessageCreate, db: Session = Depends(get_db)) -> MessageRead:
    venue = db.get(Venue, venue_id)
    if not venue:
        raise HTTPException(status_code=404, detail="Venue not found")

    sender = db.get(User, payload.sent_by)
    if not sender:
        raise HTTPException(status_code=404, detail="Sender not found")
    if sender.role not in (UserRole.business_owner, UserRole.platform_owner):
        raise HTTPException(status_code=403, detail="Admin role required to send messages")
    if sender.role == UserRole.business_owner and venue.owner_id != sender.id:
        raise HTTPException(status_code=403, detail="Sender does not own this venue")

    msg = Message(venue_id=venue_id, **payload.model_dump())
    db.add(msg)
    db.flush()
    log_action(
        db,
        actor_id=payload.sent_by,
        action_type="message.sent",
        venue_id=venue_id,
        target_type="message",
        target_id=msg.id,
        metadata={"message_type": payload.message_type.value, "channel": payload.channel.value},
    )
    db.commit()
    db.refresh(msg)

    return MessageRead(
        id=msg.id,
        venue_id=msg.venue_id,
        sent_by=msg.sent_by,
        message_type=msg.message_type,
        content=msg.content,
        recipient_count=msg.recipient_count,
        channel=msg.channel,
        sent_at=msg.sent_at,
    )


@router.get("/{venue_id}/messages", response_model=list[MessageRead])
def list_messages(venue_id: str, db: Session = Depends(get_db)) -> list[MessageRead]:
    rows = db.execute(select(Message).where(Message.venue_id == venue_id).order_by(Message.sent_at.desc())).scalars().all()
    return [
        MessageRead(
            id=m.id,
            venue_id=m.venue_id,
            sent_by=m.sent_by,
            message_type=m.message_type,
            content=m.content,
            recipient_count=m.recipient_count,
            channel=m.channel,
            sent_at=m.sent_at,
        )
        for m in rows
    ]
