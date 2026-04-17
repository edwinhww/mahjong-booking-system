# Mahjong Booking System (Mockup + API Scaffold)

This workspace now includes:

- Mobile-first frontend mockup at `frontend/index.html`
- FastAPI backend with core entities, booking flow, and audit hooks
- Local SQLite default (easy start)
- Heroku-ready runtime files (`Procfile`, `runtime.txt`)

## Project Structure

- `frontend/index.html`: interactive mobile mockup (EN / Traditional Chinese / Simplified Chinese)
- `app/main.py`: API app and frontend serving entry
- `app/models.py`: SQLAlchemy data model
- `app/routers/*`: API modules
- `app/services/booking_engine.py`: lock/cooldown logic
- `app/seed.py`: demo data seeder

## 1. Local Setup (Windows PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

## 2. Run Database Seed

```powershell
python -m app.seed
```

Seeded demo users:

- Platform owner: `+44 7700 900001` / `owner1234`
- Business owner: `+44 7700 900002` / `admin1234`
- Player: `+44 7700 900456` / `player1234`

## 3. Run App

```powershell
uvicorn app.main:app --reload --port 8000
```

Open:

- Frontend: `http://127.0.0.1:8000/`
- Swagger API docs: `http://127.0.0.1:8000/docs`
- Health: `http://127.0.0.1:8000/api/v1/health`

## 4. Useful API Endpoints

- `POST /api/v1/auth/register`
- `POST /api/v1/auth/login`
- `GET /api/v1/venues`
- `POST /api/v1/venues/{venue_id}/join`
- `PATCH /api/v1/venues/{venue_id}/players/{player_id}/approve?approver_id=...`
- `GET /api/v1/venues/{venue_id}/timeslots`
- `POST /api/v1/timeslots/{timeslot_id}/book`
- `DELETE /api/v1/bookings/{booking_id}?actor_id=...`
- `PATCH /api/v1/bookings/{booking_id}/unlock?admin_id=...`
- `POST /api/v1/venues/{venue_id}/messages`
- `GET /api/v1/venues/{venue_id}/audit`
- `POST /api/v1/jobs/lock-expired`

## 5. Heroku Deployment

1. Create app and add Postgres addon.
2. Set config vars (`DATABASE_URL` is provided by Postgres addon).
3. Deploy:

```powershell
git push heroku HEAD:main
```

4. Run release seed (already in `Procfile`) or manually:

```powershell
heroku run "python -m app.seed" --app <your-app-name>
```

## 6. Notes

- Current auth token is placeholder (`demo-token-*`), suitable for scaffold/demo only.
- Next production steps: JWT auth, permission middleware, migrations (Alembic), background scheduler worker.
