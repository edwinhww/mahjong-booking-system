from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.database import engine
from app.models import Base, User, UserRole, UserStatus
from passlib.context import CryptContext
from datetime import date, time, timedelta
from app.models import Venue, VenuePlayer, VenuePlayerStatus, Timeslot, TimeslotStatus, VenueProfile

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def ensure_schema() -> None:
    Base.metadata.create_all(bind=engine)

    inspector = inspect(engine)
    tables = inspector.get_table_names()

    # --- mahjoh_t_users ---
    if "mahjoh_t_users" in tables:
        user_cols = {c["name"] for c in inspector.get_columns("mahjoh_t_users")}
        user_stmts = []
        if "must_change_password" not in user_cols:
            user_stmts.append("ALTER TABLE mahjoh_t_users ADD COLUMN must_change_password BOOLEAN NOT NULL DEFAULT FALSE")
        if user_stmts:
            with engine.begin() as conn:
                for s in user_stmts:
                    conn.execute(text(s))

    # --- mahjoh_t_venue_profiles ---
    if "mahjoh_t_venue_profiles" not in tables:
        _bootstrap_demo_users()
        return

    existing = {column["name"] for column in inspector.get_columns("mahjoh_t_venue_profiles")}
    statements = []
    if "nudge_window_minutes" not in existing:
        statements.append("ALTER TABLE mahjoh_t_venue_profiles ADD COLUMN nudge_window_minutes INTEGER NOT NULL DEFAULT 60")
    if "nudge_message_template" not in existing:
        statements.append(
            "ALTER TABLE mahjoh_t_venue_profiles ADD COLUMN nudge_message_template TEXT NOT NULL DEFAULT 'Hi {player_name}, we are filling a table around {slot_time}. Want to join today''s game?'"
        )
    if "reminder_lead_minutes" not in existing:
        statements.append("ALTER TABLE mahjoh_t_venue_profiles ADD COLUMN reminder_lead_minutes INTEGER NOT NULL DEFAULT 30")
    if "reminder_message_template" not in existing:
        statements.append(
            "ALTER TABLE mahjoh_t_venue_profiles ADD COLUMN reminder_message_template TEXT NOT NULL DEFAULT 'Hi {player_name}, this is a reminder that your Mahjong game starts at {slot_time} today.'"
        )

    if not statements:
        _bootstrap_demo_users()
        return

    with engine.begin() as conn:
        for statement in statements:
            conn.execute(text(statement))

    # Bootstrap demo users
    _bootstrap_demo_users()


def _bootstrap_demo_users() -> None:
    """Create demo users for testing if they don't already exist."""
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        # Demo Player
        existing_player = db.query(User).filter(User.phone == "+85291234567").first()
        if not existing_player:
            player = User(
                name="Wei Lin",
                phone="+85291234567",
                email="player@example.com",
                password_hash=pwd_context.hash("1234"),
                role=UserRole.player,
                status=UserStatus.active,
                must_change_password=False,
            )
            db.add(player)

        # Demo Business Owner
        existing_owner = db.query(User).filter(User.phone == "+85298765432").first()
        if not existing_owner:
            owner = User(
                name="Dragon Palace",
                phone="+85298765432",
                email="owner@example.com",
                password_hash=pwd_context.hash("1234"),
                role=UserRole.business_owner,
                status=UserStatus.active,
                must_change_password=False,
            )
            db.add(owner)

        # Demo Platform Admin
        existing_admin = db.query(User).filter(User.phone == "+85287654321").first()
        if not existing_admin:
            admin = User(
                name="Platform Admin",
                phone="+85287654321",
                email="admin@example.com",
                password_hash=pwd_context.hash("1234"),
                role=UserRole.platform_owner,
                status=UserStatus.active,
                must_change_password=False,
            )
            db.add(admin)

        db.commit()

        # Re-query to get IDs after commit
        owner = db.query(User).filter(User.phone == "+85298765432").first()
        player = db.query(User).filter(User.phone == "+85291234567").first()

        # Demo venue owned by business owner
        if owner:
            existing_venue = db.query(Venue).filter(Venue.owner_id == owner.id).first()
            if not existing_venue:
                venue = Venue(
                    owner_id=owner.id,
                    name="Dragon Palace MJ",
                    opening_time=time(10, 0),
                    closing_time=time(22, 0),
                    table_count=4,
                    session_duration_hrs=2,
                    cooldown_minutes=30,
                    session_fee=80,
                    platform_fee_pct=5,
                    status="active",
                )
                db.add(venue)
                db.flush()

                # Venue profile
                db.add(VenueProfile(venue_id=venue.id))

                # Link player to venue as approved
                if player:
                    db.add(VenuePlayer(
                        venue_id=venue.id,
                        player_id=player.id,
                        status=VenuePlayerStatus.approved,
                    ))

                # Generate timeslots for today and tomorrow (4 tables, slots at 10,12,14,16,18,20)
                for day_offset in range(2):
                    slot_date = date.today() + timedelta(days=day_offset)
                    for hour in [10, 12, 14, 16, 18, 20]:
                        start = time(hour, 0)
                        end = time(hour + 2, 0)
                        for table_num in range(1, 5):
                            db.add(Timeslot(
                                venue_id=venue.id,
                                date=slot_date,
                                start_time=start,
                                end_time=end,
                                table_number=table_num,
                                status=TimeslotStatus.open,
                            ))

                db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()