from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models


def cooldown_expiry(minutes: int) -> datetime:
    return datetime.utcnow() + timedelta(minutes=minutes)


def lock_expired_bookings(db: Session) -> int:
    now = datetime.utcnow()
    query = select(models.Booking).where(
        models.Booking.status == models.BookingStatus.cooling_down,
        models.Booking.cooldown_expires <= now,
    )
    rows = db.execute(query).scalars().all()

    for booking in rows:
        booking.status = models.BookingStatus.locked
        booking.locked_at = now

    if rows:
        db.commit()
    return len(rows)


def update_timeslot_if_full(db: Session, timeslot_id: str, performed_by: str) -> None:
    total_active = db.scalar(
        select(func.count(models.Booking.id)).where(
            models.Booking.timeslot_id == timeslot_id,
            models.Booking.status != models.BookingStatus.cancelled,
        )
    )

    timeslot = db.get(models.Timeslot, timeslot_id)
    if not timeslot:
        return

    if total_active and total_active >= 4 and timeslot.status != models.TimeslotStatus.full:
        timeslot.status = models.TimeslotStatus.full
        venue = db.get(models.Venue, timeslot.venue_id)
        if venue:
            session_fee = float(venue.session_fee)
            platform_fee = round(session_fee * float(venue.platform_fee_pct) / 100, 2)
            db.add(
                models.AuditLog(
                    venue_id=venue.id,
                    action_type=models.AuditActionType.table_confirmed,
                    reference_id=timeslot.id,
                    session_fee=session_fee,
                    platform_fee=platform_fee,
                    performed_by=performed_by,
                )
            )
        db.commit()
