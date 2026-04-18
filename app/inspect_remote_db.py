from sqlalchemy import text

from app.database import engine


def main() -> None:
    with engine.connect() as conn:
        tables = [
            row[0]
            for row in conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")
            ).fetchall()
        ]
        print(f"table_count={len(tables)}")
        for name in tables:
            count = conn.execute(text(f'SELECT COUNT(*) FROM "{name}"')).scalar_one()
            print(f"{name}={count}")


if __name__ == "__main__":
    main()