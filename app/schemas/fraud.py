"""Schemas FraudLog & OCR."""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict

from app.models.fraud_log import FraudType


class FraudLogOut(BaseModel):
    id: int
    penerima_id: int
    related_penerima_id: Optional[int]
    fraud_type: FraudType
    similarity_score: float
    alasan: str
    detail: Optional[str]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class FraudListResponse(BaseModel):
    total: int
    items: List[FraudLogOut]


class OCRResult(BaseModel):
    nik: Optional[str] = None
    nama: Optional[str] = None
    tempat_lahir: Optional[str] = None
    tanggal_lahir: Optional[str] = None
    jenis_kelamin: Optional[str] = None
    alamat: Optional[str] = None
    rt_rw: Optional[str] = None
    kelurahan: Optional[str] = None
    kecamatan: Optional[str] = None
    agama: Optional[str] = None
    status_perkawinan: Optional[str] = None
    pekerjaan: Optional[str] = None
    raw_text: Optional[str] = None
    confidence: float = 0.0
