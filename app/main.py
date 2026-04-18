from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from app.database import Base, engine, get_db
from app.db_schema import ensure_schema
from app.models import User, UserRole
from app.routers import action_audit, audit, auth, bookings, catalog, management, messages, orders, timeslots, venues
from app.schemas import HealthResponse
from app.services.booking_engine import lock_expired_bookings

ensure_schema()

app = FastAPI(title="Mahjong Booking System", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/v1")
app.include_router(venues.router, prefix="/api/v1")
app.include_router(timeslots.router, prefix="/api/v1")
app.include_router(bookings.router, prefix="/api/v1")
app.include_router(messages.router, prefix="/api/v1")
app.include_router(audit.router, prefix="/api/v1")
app.include_router(catalog.router, prefix="/api/v1")
app.include_router(orders.router, prefix="/api/v1")
app.include_router(management.router, prefix="/api/v1")
app.include_router(action_audit.router, prefix="/api/v1")


@app.get("/api/v1/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.post("/api/v1/jobs/lock-expired")
def run_lock_job(db: Session = Depends(get_db)) -> dict[str, int]:
    locked = lock_expired_bookings(db)
    return {"locked": locked}


@app.get("/api/v1/bootstrap")
def bootstrap(db: Session = Depends(get_db)) -> dict[str, int]:
    users = db.query(User).count()
    players = db.query(User).filter(User.role == UserRole.player).count()
    return {"users": users, "players": players}


frontend_dir = Path(__file__).resolve().parents[1] / "frontend"
if frontend_dir.exists():
    app.mount("/assets", StaticFiles(directory=frontend_dir), name="assets")

uploads_dir = Path(__file__).resolve().parents[1] / "uploads"
uploads_dir.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=uploads_dir), name="uploads")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(frontend_dir / "index.html")
