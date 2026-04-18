from app.db_schema import ensure_schema


def run_init_db() -> None:
    ensure_schema()


if __name__ == "__main__":
    run_init_db()
    print("Database schema initialized")
