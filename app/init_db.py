from app.database import Base, engine


def run_init_db() -> None:
    Base.metadata.create_all(bind=engine)


if __name__ == "__main__":
    run_init_db()
    print("Database schema initialized")
