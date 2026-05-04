"""Schemas Distribusi."""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.distribusi import DistribusiStatus


class DistribusiCreate(BaseModel):
    penerima_id: int
    jenis_bantuan: str = Field(..., min_length=2, max_length=100)
    nominal: float = Field(0.0, ge=0)
    keterangan: Optional[str] = None


class DistribusiOut(BaseModel):
    id: int
    no_seri: str
    penerima_id: int
    petugas_id: Optional[int]
    jenis_bantuan: str
    nominal: float
    keterangan: Optional[str]
    status: DistribusiStatus
    tanggal_distribusi: datetime
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ScanQRRequest(BaseModel):
    qr_payload: str = Field(..., description="Isi string hasil scan QR")
    jenis_bantuan: str = Field(..., min_length=2, max_length=100)
    nominal: float = Field(0.0, ge=0)
    keterangan: Optional[str] = None
    lokasi_lat: Optional[float] = Field(None, description="GPS latitude (opsional)")
    lokasi_lng: Optional[float] = Field(None, description="GPS longitude (opsional)")


class ScanPreviewRequest(BaseModel):
    qr_payload: str = Field(..., description="Isi string hasil scan QR")


class ScanPreviewResponse(BaseModel):
    valid: bool
    error: Optional[str] = None

    penerima_id: Optional[int] = None
    nik: Optional[str] = None
    nama: Optional[str] = None
    alamat: Optional[str] = None
    no_telp: Optional[str] = None
    kode_seri: Optional[str] = None
    is_active: bool = True
    kategori: List[str] = Field(default_factory=list)

    # Status distribusi bulan ini (kategori "Penerima Bulanan")
    is_bulanan: bool = False
    sudah_terima_bulan_ini: bool = False
    bulan_ini: Optional[int] = None
    tahun_ini: Optional[int] = None
    distribusi_bulanan_id: Optional[int] = None  # untuk konfirmasi cepat

    # Status distribusi umum
    status_bantuan: Optional[str] = None
    fraud_flag: bool = False
    fraud_reason: Optional[str] = None

    # Warning untuk UI
    warnings: List[str] = Field(default_factory=list)
