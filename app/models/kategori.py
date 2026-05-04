"""Model Kategori penerima bantuan.

4 kategori default WAJIB ada (di-seed) dan TIDAK BOLEH dihapus:
- Penerima Bulanan (weight 0.7)
- Fakir Miskin     (weight 1.0)
- Anak Yatim Piatu (weight 0.85)
- Disabilitas      (weight 0.9)

Kategori baru bisa ditambahkan kapan saja oleh admin.
"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Kategori(Base):
    __tablename__ = "kategori"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    nama: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    deskripsi: Mapped[str | None] = mapped_column(String(255), nullable=True)
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    # is_default = TRUE => kategori bawaan, tidak boleh dihapus
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    # Relationships - many-to-many ke Penerima lewat PenerimaKategori
    penerima_assoc = relationship(
        "PenerimaKategori",
        back_populates="kategori",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Kategori {self.nama} w={self.weight}>"
