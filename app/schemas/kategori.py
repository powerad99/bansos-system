"""Schemas Kategori."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class KategoriBase(BaseModel):
    nama: str = Field(..., min_length=2, max_length=100)
    deskripsi: Optional[str] = None
    weight: float = Field(0.5, ge=0.0, le=1.0)


class KategoriCreate(KategoriBase):
    pass


class KategoriUpdate(BaseModel):
    nama: Optional[str] = None
    deskripsi: Optional[str] = None
    weight: Optional[float] = Field(None, ge=0.0, le=1.0)
    is_active: Optional[bool] = None


class KategoriOut(KategoriBase):
    id: int
    is_default: bool
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
