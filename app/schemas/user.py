"""Schemas untuk User & Auth."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, computed_field

from app.models.user import ROLE_LABEL, UserRole


# ── Daftar task permissions yang tersedia ────────────────────────────────────

AVAILABLE_PERMISSIONS = [
    "entri_penerima",
    "distribusi",
    "pendataan_bulanan",
    "distribusi_bulanan",
    "distribusi_sosial",
    "laporan_distribusi",
    "database_bip",
]


# ── Base & Output ────────────────────────────────────────────────────────────

class UserBase(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    full_name: str = Field(..., min_length=2, max_length=128)
    email: Optional[str] = None
    no_telp: Optional[str] = Field(None, max_length=20)
    keterangan: Optional[str] = None
    role: UserRole = UserRole.PETUGAS


class UserOut(UserBase):
    id: int
    is_active: bool
    last_login: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    @computed_field
    @property
    def role_label(self) -> str:
        return ROLE_LABEL.get(self.role, self.role.value)

    permissions: List[str] = []     # nama task permissions
    kategori_ids: List[int] = []    # ID kategori yang boleh diakses (kosong = semua)

    model_config = ConfigDict(from_attributes=True)


# ── Create ───────────────────────────────────────────────────────────────────

class UserCreate(UserBase):
    password: str = Field(..., min_length=6)
    email: Optional[EmailStr] = None
    permissions: List[str] = Field(
        default=[],
        description=(
            "Task yang diizinkan untuk petugas. "
            "Kosong = Administrator/Admin (tidak perlu). "
            f"Pilihan: {AVAILABLE_PERMISSIONS}"
        ),
    )
    kategori_ids: List[int] = Field(
        default=[],
        description="ID kategori yang boleh diakses. Kosong = semua kategori.",
    )


# ── Update ───────────────────────────────────────────────────────────────────

class UserUpdate(BaseModel):
    """Admin: update user mana saja. User biasa: update profil sendiri."""
    full_name: Optional[str] = Field(None, min_length=2, max_length=128)
    email: Optional[EmailStr] = None
    no_telp: Optional[str] = Field(None, max_length=20)
    keterangan: Optional[str] = None
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None
    permissions: Optional[List[str]] = Field(
        None,
        description="None = jangan ubah. [] = hapus semua. [...] = ganti dengan daftar ini.",
    )
    kategori_ids: Optional[List[int]] = Field(
        None,
        description="None = jangan ubah. [] = akses semua kategori. [...] = batasi ke daftar ini.",
    )


# ── Password ─────────────────────────────────────────────────────────────────

class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str = Field(..., min_length=6)


class ResetPasswordRequest(BaseModel):
    new_password: str = Field(..., min_length=6)


# ── List ─────────────────────────────────────────────────────────────────────

class UserListResponse(BaseModel):
    total: int
    page: int
    size: int
    items: List[UserOut]


# ── Auth ─────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut
