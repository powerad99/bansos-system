"""Schemas Penerima."""
from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.penerima import PriorityLevel, PenerimaStatus
from app.schemas.kategori import KategoriOut


class PenerimaBase(BaseModel):
    nik: str = Field(..., min_length=16, max_length=16, pattern=r"^\d{16}$")
    nama: str = Field(..., min_length=2, max_length=150)
    tempat_lahir: Optional[str] = None
    tanggal_lahir: Optional[date] = None
    jenis_kelamin: Optional[str] = Field(None, pattern=r"^(L|P)$")
    alamat: str
    no_telp: Optional[str] = None
    penghasilan: float = Field(0.0, ge=0)
    jumlah_tanggungan: int = Field(0, ge=0)
    status_rumah: Optional[str] = None

    @field_validator("nik")
    @classmethod
    def validate_nik(cls, v: str) -> str:
        if not v.isdigit() or len(v) != 16:
            raise ValueError("NIK harus 16 digit angka")
        return v


class PenerimaCreate(PenerimaBase):
    kategori_ids: List[int] = Field(default_factory=list, description="Multi-kategori")


class PenerimaUpdate(BaseModel):
    nama: Optional[str] = None
    tempat_lahir: Optional[str] = None
    tanggal_lahir: Optional[date] = None
    jenis_kelamin: Optional[str] = None
    alamat: Optional[str] = None
    no_telp: Optional[str] = None
    penghasilan: Optional[float] = Field(None, ge=0)
    jumlah_tanggungan: Optional[int] = Field(None, ge=0)
    status_rumah: Optional[str] = None
    kategori_ids: Optional[List[int]] = None
    is_active: Optional[bool] = None


class PenerimaOut(PenerimaBase):
    id: int
    kode_seri: Optional[str] = None
    status_bantuan: PenerimaStatus = PenerimaStatus.MENUNGGU_DISTRIBUSI
    created_by_id: Optional[int] = None
    priority_score: float
    priority_level: PriorityLevel
    fraud_flag: bool
    fraud_reason: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    kategori: List[KategoriOut] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class PenerimaListResponse(BaseModel):
    total: int
    page: int
    size: int
    items: List[PenerimaOut]
