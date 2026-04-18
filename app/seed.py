from datetime import time

from sqlalchemy import select

from app.database import Base, SessionLocal, engine
from app.models import User, UserRole, Venue, VenuePlayer, VenuePlayerStatus
from app.security import hash_password


def run_seed() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        owner = db.scalar(select(User).where(User.phone == "+44 7700 900001"))
        if not owner:
            owner = User(
                name="Platform Owner",
                phone="+44 7700 900001",
                password_hash=hash_password("1234"),
                role=UserRole.platform_owner,
            )
            db.add(owner)

        business = db.scalar(select(User).where(User.phone == "+44 7700 900002"))
        if not business:
            business = User(
                name="Dragon Palace Admin",
                phone="+44 7700 900002",
                password_hash=hash_password("1234"),
                role=UserRole.business_owner,
            )
            db.add(business)

        player = db.scalar(select(User).where(User.phone == "+44 7700 900456"))
        if not player:
            player = User(
                name="Wei Lin",
                phone="+44 7700 900456",
                password_hash=hash_password("1234"),
                role=UserRole.player,
            )
            db.add(player)

        db.flush()

        venue = db.scalar(select(Venue).where(Venue.name == "Dragon Palace MJ"))
        if not venue:
            venue = Venue(
                owner_id=business.id,
                name="Dragon Palace MJ",
                opening_time=time(10, 0),
                closing_time=time(22, 0),
                table_count=4,
                session_duration_hrs=2,
                cooldown_minutes=30,
                session_fee=40,
                platform_fee_pct=5,
            )
            db.add(venue)
            db.flush()

        membership = db.scalar(select(VenuePlayer).where(VenuePlayer.venue_id == venue.id, VenuePlayer.player_id == player.id))
        if not membership:
            db.add(
                VenuePlayer(
                    venue_id=venue.id,
                    player_id=player.id,
                    status=VenuePlayerStatus.approved,
                    approved_by=business.id,
                )
            )

        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    run_seed()
    print("Seed complete")
