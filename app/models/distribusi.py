"""Model Distribusi Bantuan."""
import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum as SAEnum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class DistribusiStatus(str, enum.Enum):
    PENDING = "PENDING"
    DISTRIBUTED = "DISTRIBUTED"
    REJECTED = "REJECTED"


class Distribusi(Base):
    __tablename__ = "distribusi"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    no_seri: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)

    penerima_id: Mapped[int] = mapped_column(
        ForeignKey("penerima.id", ondelete="CASCADE"), nullable=False, index=True
    )
    petugas_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    jenis_bantuan: Mapped[str] = mapped_column(String(100), nullable=False)
    nominal: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    keterangan: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[DistribusiStatus] = mapped_column(
        SAEnum(DistribusiStatus, name="distribusi_status"),
        default=DistribusiStatus.PENDING,
        nullable=False,
    )

    tanggal_distribusi: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    # Relationships
    penerima = relationship("Penerima", back_populates="distribusi_history")
    petugas = relationship("User", back_populates="distribusi_dilakukan")

    def __repr__(self) -> str:
        return f"<Distribusi {self.no_seri} -> penerima_id={self.penerima_id}>"
