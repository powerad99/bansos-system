"""Auth service — login, create, update, list user."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session, selectinload

from app.core.security import hash_password, verify_password
from app.models import User, UserRole
from app.models.permission import UserCategory, UserPermission


def authenticate(db: Session, username: str, password: str) -> Optional[User]:
    user = db.query(User).filter(User.username == username).first()
    if not user or not user.is_active:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


def update_last_login(db: Session, user: User) -> None:
    user.last_login = datetime.utcnow()
    db.commit()


def create_user(
    db: Session,
    username: str,
    password: str,
    full_name: str,
    role: UserRole = UserRole.PETUGAS,
    email: Optional[str] = None,
    no_telp: Optional[str] = None,
    keterangan: Optional[str] = None,
) -> User:
    user = User(
        username=username,
        full_name=full_name,
        email=email or None,
        no_telp=no_telp,
        keterangan=keterangan,
        password_hash=hash_password(password),
        role=role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def update_user(
    db: Session,
    user: User,
    full_name: Optional[str] = None,
    email: Optional[str] = None,
    no_telp: Optional[str] = None,
    keterangan: Optional[str] = None,
    role: Optional[UserRole] = None,
    is_active: Optional[bool] = None,
) -> User:
    if full_name is not None:
        user.full_name = full_name
    if email is not None:
        user.email = email or None
    if no_telp is not None:
        user.no_telp = no_telp
    if keterangan is not None:
        user.keterangan = keterangan
    if role is not None:
        user.role = role
    if is_active is not None:
        user.is_active = is_active
    user.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(user)
    return user


def change_password(db: Session, user: User, new_password: str) -> None:
    user.password_hash = hash_password(new_password)
    user.updated_at = datetime.utcnow()
    db.commit()


def list_users(
    db: Session,
    page: int = 1,
    size: int = 20,
    q: Optional[str] = None,
    role: Optional[UserRole] = None,
    is_active: Optional[bool] = None,
):
    query = db.query(User)
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(User.username.ilike(like), User.full_name.ilike(like), User.email.ilike(like))
        )
    if role is not None:
        query = query.filter(User.role == role)
    if is_active is not None:
        query = query.filter(User.is_active == is_active)
    total = query.count()
    rows = (
        query
        .options(
            selectinload(User.user_permissions).selectinload(UserPermission.permission),
            selectinload(User.user_categories),
        )
        .order_by(User.created_at.desc())
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )
    return total, rows
