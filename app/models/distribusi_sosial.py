"""Model DistribusiSosial — distribusi otomatis bulanan untuk 3 kategori sosial.

Kategori yang dilayani: Fakir Miskin, Disabilitas, Anak Yatim Piatu.
1 penerima hanya boleh masuk 1 kategori (enforced di level aplikasi).
Setiap penerima mendapat 12 entri per tahun (Jan–Des).
"""
import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Integer, SmallInteger, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class StatusSosial(str, enum.Enum):
    BELUM_DITERIMA = "BELUM_DITERIMA"
    SUDAH_DITERIMA = "SUDAH_DITERIMA"


class DistribusiSosial(Base):
    __tablename__ = "distribusi_sosial"
    __table_args__ = (
        UniqueConstraint("penerima_id", "bulan", "tahun", name="uq_distribusi_sosial"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    penerima_id: Mapped[int] = mapped_column(
        ForeignKey("penerima.id", ondelete="CASCADE"), nullable=False, index=True
    )
    bulan: Mapped[int] = mapped_column(SmallInteger, nullable=False)   # 1–12
    tahun: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    status: Mapped[StatusSosial] = mapped_column(
        SAEnum(StatusSosial, name="status_sosial"),
        default=StatusSosial.BELUM_DITERIMA,
        nullable=False,
        index=True,
    )

    confirmed_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    penerima = relationship("Penerima")
    confirmed_by = relationship("User", foreign_keys=[confirmed_by_id])

    def __repr__(self) -> str:
        return f"<DistribusiSosial penerima={self.penerima_id} {self.bulan}/{self.tahun} {self.status}>"
