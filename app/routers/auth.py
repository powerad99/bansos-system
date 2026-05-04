"""Auth endpoints: POST /auth/login, POST /auth/register (alias admin).

Register user baru sebaiknya lewat POST /users (router users.py).
Endpoint /auth/register tetap ada untuk backward compat.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.config import settings
from app.core.security import create_access_token
from app.database import get_db
from app.dependencies import require_admin
from app.models import User, UserRole
from app.schemas.user import LoginRequest, TokenResponse, UserCreate, UserOut
from app.services.auth_service import authenticate, create_user, update_last_login

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = authenticate(db, payload.username, payload.password)
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Username / password salah")

    update_last_login(db, user)

    token = create_access_token(
        subject=user.id,
        extra={"role": user.role.value, "username": user.username},
    )
    return TokenResponse(
        access_token=token,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=UserOut.model_validate(user),
    )


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(
    payload: UserCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Alias untuk POST /users — hanya admin."""
    if db.query(User).filter(User.username == payload.username).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Username sudah dipakai")
    return create_user(
        db=db,
        username=payload.username,
        password=payload.password,
        full_name=payload.full_name,
        role=payload.role or UserRole.PETUGAS,
        email=payload.email,
        no_telp=payload.no_telp,
        keterangan=payload.keterangan,
    )
