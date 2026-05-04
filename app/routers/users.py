"""Manajemen Pengguna — CRUD lengkap.

Tingkatan role:
  1. Administrator — akses penuh + kelola user (buat, edit, hapus)
  2. Admin         — akses data & laporan, tidak bisa kelola user
  3. Petugas       — dibatasi task permissions + kategori

Endpoint:
  GET    /users/permissions/available  — daftar semua task permissions (admin)
  GET    /users                        — list semua user (admin)
  POST   /users                        — buat user baru (admin)
  GET    /users/me                     — profil sendiri (semua role)
  PUT    /users/me                     — update profil sendiri
  PUT    /users/me/password            — ganti password sendiri
  GET    /users/{id}                   — detail user (admin)
  PUT    /users/{id}                   — update user + permissions + kategori (admin)
  DELETE /users/{id}                   — nonaktifkan / hapus user (admin)
  POST   /users/{id}/activate          — aktifkan kembali user (admin)
  POST   /users/{id}/reset-password    — reset password (admin)
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session, selectinload

from app.core.security import verify_password
from app.database import get_db
from app.dependencies import get_current_user, require_admin, require_manajemen
from app.models import Kategori, User, UserRole
from app.models.permission import Permission, UserCategory, UserPermission
from app.schemas.user import (
    AVAILABLE_PERMISSIONS,
    ChangePasswordRequest,
    ResetPasswordRequest,
    UserCreate,
    UserListResponse,
    UserOut,
    UserUpdate,
)
from app.services.auth_service import (
    change_password,
    create_user,
    list_users,
    update_user,
)

router = APIRouter(prefix="/users", tags=["users"])


# Helper: load user dengan permissions & kategori
def _load_user_full(db: Session, user_id: int) -> User | None:
    return (
        db.query(User)
        .options(
            selectinload(User.user_permissions).selectinload(UserPermission.permission),
            selectinload(User.user_categories),
        )
        .filter(User.id == user_id)
        .first()
    )


def _user_out(user: User) -> dict:
    data = UserOut.model_validate(user).model_dump()
    data["permissions"] = [up.permission.name for up in (user.user_permissions or [])]
    data["kategori_ids"] = [uc.category_id for uc in (user.user_categories or [])]
    return data


def _set_permissions(db: Session, user_id: int, perm_names: List[str]) -> None:
    if perm_names:
        invalid = set(perm_names) - set(AVAILABLE_PERMISSIONS)
        if invalid:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Permission tidak dikenal: {sorted(invalid)}. Tersedia: {AVAILABLE_PERMISSIONS}",
            )
    db.query(UserPermission).filter(UserPermission.user_id == user_id).delete(synchronize_session=False)
    for name in perm_names:
        perm = db.query(Permission).filter(Permission.name == name).first()
        if perm:
            db.add(UserPermission(user_id=user_id, permission_id=perm.id))


def _set_kategori(db: Session, user_id: int, kategori_ids: List[int]) -> None:
    if kategori_ids:
        found = db.query(Kategori.id).filter(Kategori.id.in_(kategori_ids)).all()
        missing = set(kategori_ids) - {r.id for r in found}
        if missing:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Kategori tidak ditemukan: {sorted(missing)}")
    db.query(UserCategory).filter(UserCategory.user_id == user_id).delete(synchronize_session=False)
    for kat_id in kategori_ids:
        db.add(UserCategory(user_id=user_id, category_id=kat_id))


# /users/me (harus sebelum /{user_id})
@router.get("/me", response_model=UserOut)
def get_me(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return _user_out(_load_user_full(db, current_user.id))


@router.put("/me", response_model=UserOut)
def update_me(payload: UserUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    data = payload.model_dump(exclude_unset=True)
    for field in ("role", "is_active", "permissions", "kategori_ids"):
        data.pop(field, None)
    new_email = data.get("email")
    if new_email and new_email != current_user.email:
        if db.query(User).filter(User.email == new_email, User.id != current_user.id).first():
            raise HTTPException(status.HTTP_409_CONFLICT, "Email sudah dipakai user lain")
    user = update_user(db, current_user, **data)
    return _user_out(_load_user_full(db, user.id))


@router.put("/me/password", status_code=status.HTTP_204_NO_CONTENT)
def change_my_password(payload: ChangePasswordRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not verify_password(payload.old_password, current_user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Password lama salah")
    change_password(db, current_user, payload.new_password)
    return None


# Referensi permissions
class PermissionRef(BaseModel):
    name: str
    label: str
    model_config = {"from_attributes": True}


@router.get("/permissions/available", response_model=List[PermissionRef])
def list_available_permissions(db: Session = Depends(get_db), _: User = Depends(require_manajemen)):
    """Daftar semua task permissions yang bisa ditetapkan ke petugas."""
    return db.query(Permission).filter(Permission.name.in_(AVAILABLE_PERMISSIONS)).order_by(Permission.name).all()


# List & buat user (administrator only)
@router.get("", response_model=UserListResponse)
def list_all_users(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    q: Optional[str] = Query(None),
    role: Optional[UserRole] = Query(None),
    is_active: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    total, rows = list_users(db, page=page, size=size, q=q, role=role, is_active=is_active)
    ids = [u.id for u in rows]
    full_rows = (
        db.query(User)
        .options(selectinload(User.user_permissions).selectinload(UserPermission.permission), selectinload(User.user_categories))
        .filter(User.id.in_(ids))
        .all()
    )
    full_map = {u.id: u for u in full_rows}
    ordered = [full_map[u.id] for u in rows if u.id in full_map]
    return {"total": total, "page": page, "size": size, "items": [_user_out(u) for u in ordered]}


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_new_user(payload: UserCreate, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    """Buat user baru + assign task permissions & kategori untuk petugas."""
    if db.query(User).filter(User.username == payload.username).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Username sudah dipakai")
    if payload.email and db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Email sudah dipakai")
    if payload.permissions:
        invalid = set(payload.permissions) - set(AVAILABLE_PERMISSIONS)
        if invalid:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Permission tidak dikenal: {sorted(invalid)}. Tersedia: {AVAILABLE_PERMISSIONS}")
    if payload.kategori_ids:
        found = {r.id for r in db.query(Kategori.id).filter(Kategori.id.in_(payload.kategori_ids)).all()}
        missing = set(payload.kategori_ids) - found
        if missing:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Kategori tidak ditemukan: {sorted(missing)}")

    user = create_user(db=db, username=payload.username, password=payload.password, full_name=payload.full_name,
                       role=payload.role, email=payload.email, no_telp=payload.no_telp, keterangan=payload.keterangan)
    if payload.permissions:
        _set_permissions(db, user.id, payload.permissions)
    if payload.kategori_ids:
        _set_kategori(db, user.id, payload.kategori_ids)
    db.commit()
    return _user_out(_load_user_full(db, user.id))


# Operasi per user (administrator only)
@router.get("/{user_id}", response_model=UserOut)
def get_user(user_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    user = _load_user_full(db, user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User tidak ditemukan")
    return _user_out(user)


@router.put("/{user_id}", response_model=UserOut)
def update_user_by_admin(user_id: int, payload: UserUpdate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    """Update data user + permissions + kategori sekaligus."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User tidak ditemukan")
    if user.id == admin.id and payload.is_active is False:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Tidak bisa menonaktifkan akun sendiri")
    data = payload.model_dump(exclude_unset=True)
    new_email = data.get("email")
    if new_email and new_email != user.email:
        if db.query(User).filter(User.email == new_email, User.id != user_id).first():
            raise HTTPException(status.HTTP_409_CONFLICT, "Email sudah dipakai user lain")
    permissions = data.pop("permissions", None)
    kategori_ids = data.pop("kategori_ids", None)
    update_user(db, user, **data)
    if permissions is not None:
        _set_permissions(db, user_id, permissions)
    if kategori_ids is not None:
        _set_kategori(db, user_id, kategori_ids)
    db.commit()
    return _user_out(_load_user_full(db, user_id))


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_user(user_id: int, hard: bool = Query(False), db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User tidak ditemukan")
    if user.id == admin.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Tidak bisa menghapus akun sendiri")
    if hard:
        db.delete(user)
    else:
        user.is_active = False
    db.commit()
    return None


@router.post("/{user_id}/activate", response_model=UserOut)
def activate_user(user_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User tidak ditemukan")
    user.is_active = True
    db.commit()
    return _user_out(_load_user_full(db, user_id))


@router.post("/{user_id}/reset-password", status_code=status.HTTP_204_NO_CONTENT)
def reset_user_password(user_id: int, payload: ResetPasswordRequest, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User tidak ditemukan")
    change_password(db, user, payload.new_password)
    return None
