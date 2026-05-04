"""Association table M2M antara Penerima <-> Kategori.

Pakai association object (bukan plain Table) supaya bisa ditambahkan
metadata seperti tanggal_masuk_kategori jika diperlukan.
"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class PenerimaKategori(Base):
    __tablename__ = "penerima_kategori"
    __table_args__ = (
        UniqueConstraint("penerima_id", "kategori_id", name="uq_penerima_kategori"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    penerima_id: Mapped[int] = mapped_column(
        ForeignKey("penerima.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kategori_id: Mapped[int] = mapped_column(
        ForeignKey("kategori.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    penerima = relationship("Penerima", back_populates="kategori_assoc")
    kategori = relationship("Kategori", back_populates="penerima_assoc")
