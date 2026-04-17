from sqlalchemy import inspect, text

from app.database import engine

TABLE_MAP = {
    "users": "mahjoh_t_users",
    "venues": "mahjoh_t_venues",
    "venue_players": "mahjoh_t_venue_players",
    "timeslots": "mahjoh_t_timeslots",
    "bookings": "mahjoh_t_bookings",
    "messages": "mahjoh_t_messages",
    "audit_log": "mahjoh_t_audit_log",
    "venue_profiles": "mahjoh_t_venue_profiles",
    "service_items": "mahjoh_t_service_items",
    "booking_orders": "mahjoh_t_booking_orders",
    "booking_order_items": "mahjoh_t_booking_order_items",
    "booking_cancellation_requests": "mahjoh_t_booking_cancellation_requests",
    "action_audit": "mahjoh_t_action_audit",
}


def quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def run() -> None:
    inspector = inspect(engine)
    existing = set(inspector.get_table_names())

    to_rename: list[tuple[str, str]] = []
    conflicts: list[tuple[str, str]] = []

    for old_name, new_name in TABLE_MAP.items():
        old_exists = old_name in existing
        new_exists = new_name in existing

        if old_exists and not new_exists:
            to_rename.append((old_name, new_name))
        elif old_exists and new_exists:
            conflicts.append((old_name, new_name))

    if conflicts:
        print("Migration halted: both old and new tables exist for some mappings.")
        for old_name, new_name in conflicts:
            print(f"  conflict: {old_name} and {new_name}")
        print("Resolve conflicts before rerunning migration.")
        return

    if not to_rename:
        print("No table renames needed. Prefix migration already applied or no source tables found.")
        return

    with engine.begin() as conn:
        for old_name, new_name in to_rename:
            stmt = text(f"ALTER TABLE {quote_ident(old_name)} RENAME TO {quote_ident(new_name)}")
            conn.execute(stmt)
            print(f"renamed: {old_name} -> {new_name}")

    print("Table prefix migration completed successfully.")


if __name__ == "__main__":
    run()
