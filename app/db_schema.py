from sqlalchemy import inspect, text

from app.database import engine
from app.models import Base


def ensure_schema() -> None:
    Base.metadata.create_all(bind=engine)

    inspector = inspect(engine)
    tables = inspector.get_table_names()
    if "mahjoh_t_venue_profiles" not in tables:
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
        return

    with engine.begin() as conn:
        for statement in statements:
            conn.execute(text(statement))