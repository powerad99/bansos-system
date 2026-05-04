"""Schemas untuk Distribusi Bulanan."""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, computed_field

from app.models.distribusi_bulanan import StatusBulanan

_NAMA_BULAN = [
    "", "Januari", "Februari", "Maret", "April", "Mei", "Juni",
    "Juli", "Agustus", "September", "Oktober", "November", "Desember",
]


class PenerimaRingkas(BaseModel):
    id: int
    nik: str
    nama: str
    kode_seri: Optional[str] = None
    alamat: str
    model_config = ConfigDict(from_attributes=True)


class PetugasRingkas(BaseModel):
    id: int
    username: str
    full_name: str
    model_config = ConfigDict(from_attributes=True)


class DistribusiBulananOut(BaseModel):
    id: int
    penerima_id: int
    bulan: int
    tahun: int
    status: StatusBulanan
    confirmed_by_id: Optional[int] = None
    confirmed_at: Optional[datetime] = None
    created_at: datetime
    penerima: Optional[PenerimaRingkas] = None
    confirmed_by: Optional[PetugasRingkas] = None

    model_config = ConfigDict(from_attributes=True)

    @computed_field
    @property
    def nama_bulan(self) -> str:
        return _NAMA_BULAN[self.bulan] if 1 <= self.bulan <= 12 else ""


class DistribusiBulananListResponse(BaseModel):
    total: int
    page: int
    size: int
    items: List[DistribusiBulananOut]
