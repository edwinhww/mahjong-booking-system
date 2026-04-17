from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.schemas import AuthResponse, LoginRequest, UserCreate, UserRead
from app.security import hash_password, verify_password
from app.services.action_audit import log_action

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserRead)
def register(payload: UserCreate, db: Session = Depends(get_db)) -> UserRead:
    exists = db.scalar(select(User).where(User.phone == payload.phone))
    if exists:
        raise HTTPException(status_code=409, detail="Phone already registered")

    user = User(
        name=payload.name,
        phone=payload.phone,
        email=payload.email,
        password_hash=hash_password(payload.password),
        role=payload.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    log_action(
        db,
        actor_id=user.id,
        action_type="auth.register",
        target_type="user",
        target_id=user.id,
        metadata={"role": user.role.value},
    )
    db.commit()
    return UserRead(id=user.id, name=user.name, phone=user.phone, role=user.role, status=user.status)


@router.post("/login", response_model=AuthResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> AuthResponse:
    user = db.scalar(select(User).where(User.phone == payload.phone))
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = f"demo-token-{user.id}"
    log_action(
        db,
        actor_id=user.id,
        action_type="auth.login",
        target_type="user",
        target_id=user.id,
        metadata={"phone": user.phone},
    )
    db.commit()
    user_data = UserRead(id=user.id, name=user.name, phone=user.phone, role=user.role, status=user.status)
    return AuthResponse(token=token, user=user_data)
