"""Shared FastAPI dependencies: auth, role-guard, permission-guard.

Matriks akses:
  ADMINISTRATOR : semua akses penuh + kelola user
  ADMIN         : semua akses data & laporan, tidak bisa kelola user
  PETUGAS       : dibatasi oleh task permissions + kategori yang ditetapkan admin

Task permissions (nama di tabel permissions):
  entri_penerima     — entri & edit data penerima
  distribusi         — distribusi bantuan
  pendataan_bulanan  — pendataan bulanan
  distribusi_bulanan — distribusi bulanan
  laporan_distribusi — lihat laporan distribusi

Kategori access (tabel user_categories):
  Kosong  → petugas bisa akses semua kategori
  Berisi  → petugas hanya bisa akses kategori yang ditugaskan
"""
from __future__ import annotations

from typing import List

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session, selectinload

from app.core.security import decode_access_token
from app.database import get_db
from app.models import User, UserRole
from app.models.permission import UserPermission

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing token")
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    sub = payload.get("sub")
    if not sub:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token claims")
    user = (
        db.query(User)
        .options(
            selectinload(User.user_permissions).selectinload(UserPermission.permission),
            selectinload(User.user_categories),
        )
        .filter(User.id == int(sub))
        .first()
    )
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found / inactive")
    return user


# ── Role guards ──────────────────────────────────────────────────────────────

def require_roles(*allowed: UserRole):
    def _dep(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Role '{user.role.value}' tidak diizinkan untuk aksi ini",
            )
        return user
    return _dep


# Hanya Administrator yang bisa kelola user
require_admin = require_roles(UserRole.ADMINISTRATOR)

# Administrator + Admin: akses data, laporan, statistik
require_manajemen = require_roles(UserRole.ADMINISTRATOR, UserRole.ADMIN)


# ── Permission helpers ───────────────────────────────────────────────────────

def has_permission(user: User, perm_name: str) -> bool:
    """True jika user punya izin task tersebut.
    Administrator & Admin selalu True."""
    if user.role in (UserRole.ADMINISTRATOR, UserRole.ADMIN):
        return True
    return any(up.permission.name == perm_name for up in user.user_permissions)


def get_allowed_category_ids(user: User) -> List[int] | None:
    """None = tidak ada batasan (akses semua kategori).
    List berisi ID = hanya kategori tersebut yang boleh diakses."""
    if user.role in (UserRole.ADMINISTRATOR, UserRole.ADMIN):
        return None  # unrestricted
    ids = [uc.category_id for uc in user.user_categories]
    return ids if ids else None  # petugas tanpa batasan kategori → akses semua


# Mapping izin → nama kategori yang otomatis didapat oleh izin tersebut.
# Tujuan: petugas dengan `pendataan_bulanan` otomatis bisa entri penerima
# Bulanan tanpa admin perlu juga assign kategorinya secara terpisah.
_PERM_IMPLIED_KATEGORI: dict[str, tuple[str, ...]] = {
    "pendataan_bulanan":  ("Penerima Bulanan",),
    "distribusi_bulanan": ("Penerima Bulanan",),
    "entri_penerima":     ("Fakir Miskin", "Disabilitas", "Anak Yatim Piatu"),
    "distribusi_sosial":  ("Fakir Miskin", "Disabilitas", "Anak Yatim Piatu"),
}


def _implied_kategori_ids(user: User, db: Session) -> List[int]:
    """Kumpulkan kategori-kategori yang otomatis diizinkan berdasarkan izin user."""
    from app.models import Kategori
    needed: set[str] = set()
    for perm_name, kat_names in _PERM_IMPLIED_KATEGORI.items():
        if has_permission(user, perm_name):
            needed.update(kat_names)
    if not needed:
        return []
    return [
        k.id for k in
        db.query(Kategori.id, Kategori.nama).filter(Kategori.nama.in_(needed)).all()
    ]


def check_category_access(
    user: User,
    penerima_kategori_ids: List[int],
    db: Session | None = None,
) -> bool:
    """True jika user punya akses ke setidaknya satu kategori penerima.
    Akses diturunkan dari `user_categories` ATAU dari kategori implisit
    berdasarkan izin (mis. `pendataan_bulanan` → Penerima Bulanan)."""
    allowed = get_allowed_category_ids(user)
    if allowed is None:
        return True
    allowed_set = set(allowed)
    if db is not None:
        allowed_set |= set(_implied_kategori_ids(user, db))
    return bool(allowed_set & set(penerima_kategori_ids))


def require_perm(perm_name: str):
    """Guard berbasis task permission. Administrator & Admin selalu lolos."""
    def _dep(user: User = Depends(get_current_user)) -> User:
        if not has_permission(user, perm_name):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Akses ditolak: butuh izin '{perm_name}'",
            )
        return user
    return _dep


# ── Shortcut guards berbasis permission ──────────────────────────────────────

def _require_entri(user: User = Depends(get_current_user)) -> User:
    """Izin untuk create/edit/delete penerima (POST/PUT/DELETE /penerima).
    Lolos jika user punya `entri_penerima` (untuk pendaftar sosial) ATAU
    `pendataan_bulanan` (untuk penerima rutin bulanan). Pembatasan kategori
    tetap berlaku via `check_category_access` di endpoint."""
    if user.role in (UserRole.ADMINISTRATOR, UserRole.ADMIN):
        return user
    if has_permission(user, "entri_penerima") or has_permission(user, "pendataan_bulanan"):
        return user
    raise HTTPException(
        status.HTTP_403_FORBIDDEN,
        "Akses ditolak: butuh izin 'entri_penerima' atau 'pendataan_bulanan'",
    )


require_entri              = _require_entri
require_distribusi         = require_perm("distribusi")
require_pendataan_bulanan  = require_perm("pendataan_bulanan")
require_distribusi_bulanan = require_perm("distribusi_bulanan")
require_laporan            = require_perm("laporan_distribusi")


def _require_export(user: User = Depends(get_current_user)) -> User:
    """Export: Administrator, Admin, atau Petugas dengan minimal 1 task permission."""
    if user.role in (UserRole.ADMINISTRATOR, UserRole.ADMIN):
        return user
    if user.user_permissions:
        return user
    raise HTTPException(
        status.HTTP_403_FORBIDDEN,
        "Akses ditolak: butuh setidaknya satu task permission untuk export",
    )


require_export = _require_export

# Alias lama agar kode lain tidak pecah
require_admin_or_petugas = require_manajemen
