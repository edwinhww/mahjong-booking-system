from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Booking, BookingStatus, Timeslot, TimeslotStatus, Venue
from app.schemas import TimeslotRead

router = APIRouter(prefix="/venues", tags=["timeslots"])


def _in_operating_window(slot_time, opening_time, closing_time) -> bool:
    """Return True if slot_time falls within the venue's operating hours.
    Handles overnight spans (e.g. 13:00 opening, 02:00 closing next day).
    """
    if opening_time < closing_time:
        # Normal same-day window
        return opening_time <= slot_time < closing_time
    else:
        # Overnight window: valid if >= opening OR < closing
        return slot_time >= opening_time or slot_time < closing_time


def _sort_slot_rows(rows: list[Timeslot], opening_time) -> list[Timeslot]:
    opening_minutes = opening_time.hour * 60 + opening_time.minute

    def sort_key(slot: Timeslot) -> tuple[int, int]:
        slot_minutes = slot.start_time.hour * 60 + slot.start_time.minute
        if slot_minutes < opening_minutes:
            slot_minutes += 24 * 60
        return (slot_minutes, slot.table_number)

    return sorted(rows, key=sort_key)


def _generate_timeslots_for_date(db: Session, venue: Venue, target_date: date) -> None:
    opening = datetime.combine(target_date, venue.opening_time)
    closing = datetime.combine(target_date, venue.closing_time)
    if closing <= opening:
        closing += timedelta(days=1)
    slot_delta = timedelta(hours=venue.session_duration_hrs)

    current = opening
    while current + slot_delta <= closing:
        # Use the actual calendar date the slot falls on (handles overnight venues)
        actual_slot_date = current.date()
        for table_num in range(1, venue.table_count + 1):
            exists = db.scalar(
                select(Timeslot).where(
                    Timeslot.venue_id == venue.id,
                    Timeslot.date == actual_slot_date,
                    Timeslot.start_time == current.time(),
                    Timeslot.table_number == table_num,
                )
            )
            if not exists:
                db.add(
                    Timeslot(
                        venue_id=venue.id,
                        date=actual_slot_date,
                        start_time=current.time(),
                        end_time=(current + slot_delta).time(),
                        table_number=table_num,
                        status=TimeslotStatus.open,
                    )
                )
        current += slot_delta


@router.get("/{venue_id}/timeslots", response_model=list[TimeslotRead])
def list_timeslots(venue_id: str, day: date | None = None, db: Session = Depends(get_db)) -> list[TimeslotRead]:
    venue = db.get(Venue, venue_id)
    if not venue:
        raise HTTPException(status_code=404, detail="Venue not found")

    target_date = day or date.today()
    # For overnight venues, also generate for the previous day so that after-midnight
    # slots (which are stored on target_date) already exist.
    _generate_timeslots_for_date(db, venue, target_date - timedelta(days=1))
    _generate_timeslots_for_date(db, venue, target_date)
    db.commit()

    rows = db.execute(
        select(Timeslot).where(Timeslot.venue_id == venue_id, Timeslot.date == target_date).order_by(Timeslot.start_time, Timeslot.table_number)
    ).scalars().all()

    # Filter out stale slots that no longer fall in the venue's current operating window
    # (e.g. leftover rows from a previous opening-time setting).
    rows = [t for t in rows if _in_operating_window(t.start_time, venue.opening_time, venue.closing_time)]

    # Filter out slots that don't align with the current session duration step.
    # e.g. if duration changed from 1 hr to 2 hrs, drop the old in-between slots.
    step_mins = venue.session_duration_hrs * 60
    opening_mins = venue.opening_time.hour * 60 + venue.opening_time.minute

    def _aligns_with_step(slot_time) -> bool:
        slot_mins = slot_time.hour * 60 + slot_time.minute
        # Normalise to minutes-from-opening (handles overnight)
        diff = (slot_mins - opening_mins) % (24 * 60)
        return diff % step_mins == 0

    rows = [t for t in rows if _aligns_with_step(t.start_time)]
    rows = _sort_slot_rows(rows, venue.opening_time)

    return [
        TimeslotRead(
            id=t.id,
            venue_id=t.venue_id,
            date=t.date,
            start_time=t.start_time,
            end_time=t.end_time,
            table_number=t.table_number,
            status=t.status.value,
        )
        for t in rows
    ]


@router.get("/{venue_id}/timeslots/window", response_model=list[TimeslotRead])
def list_timeslots_window(
    venue_id: str,
    from_day: date | None = None,
    days: int = 2,
    one_seat_left_only: bool = False,
    db: Session = Depends(get_db),
) -> list[TimeslotRead]:
    venue = db.get(Venue, venue_id)
    if not venue:
        raise HTTPException(status_code=404, detail="Venue not found")

    start_day = from_day or date.today()
    days = max(1, min(days, 14))
    end_day = start_day + timedelta(days=days - 1)

    cursor = start_day
    while cursor <= end_day:
        _generate_timeslots_for_date(db, venue, cursor)
        cursor += timedelta(days=1)
    db.commit()

    slots = db.execute(
        select(Timeslot)
        .where(Timeslot.venue_id == venue_id, Timeslot.date >= start_day, Timeslot.date <= end_day)
        .order_by(Timeslot.date, Timeslot.start_time, Timeslot.table_number)
    ).scalars().all()

    if not one_seat_left_only:
        slots = _sort_slot_rows(slots, venue.opening_time)
        return [
            TimeslotRead(
                id=t.id,
                venue_id=t.venue_id,
                date=t.date,
                start_time=t.start_time,
                end_time=t.end_time,
                table_number=t.table_number,
                status=t.status.value,
            )
            for t in slots
        ]

    slots = _sort_slot_rows(slots, venue.opening_time)
    output: list[TimeslotRead] = []
    for t in slots:
        active_count = db.scalar(
            select(func.count(Booking.id)).where(
                Booking.timeslot_id == t.id,
                Booking.status != BookingStatus.cancelled,
            )
        )
        if active_count == 3:
            output.append(
                TimeslotRead(
                    id=t.id,
                    venue_id=t.venue_id,
                    date=t.date,
                    start_time=t.start_time,
                    end_time=t.end_time,
                    table_number=t.table_number,
                    status=t.status.value,
                )
            )
    return output
