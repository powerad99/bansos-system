"""Model Fraud Log - audit trail kecurigaan duplikasi/manipulasi data."""
import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum as SAEnum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class FraudType(str, enum.Enum):
    NIK_DUPLICATE = "NIK_DUPLICATE"
    NAMA_SIMILAR = "NAMA_SIMILAR"
    ALAMAT_SIMILAR = "ALAMAT_SIMILAR"
    COMBO_SIMILAR = "COMBO_SIMILAR"
    DOUBLE_DISTRIBUSI = "DOUBLE_DISTRIBUSI"
    OTHER = "OTHER"


class FraudLog(Base):
    __tablename__ = "fraud_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    penerima_id: Mapped[int] = mapped_column(
        ForeignKey("penerima.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # ID penerima lain yang jadi pembanding (kalau ada)
    related_penerima_id: Mapped[int | None] = mapped_column(
        ForeignKey("penerima.id", ondelete="SET NULL"), nullable=True
    )

    fraud_type: Mapped[FraudType] = mapped_column(
        SAEnum(FraudType, name="fraud_type"), nullable=False
    )
    similarity_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    alasan: Mapped[str] = mapped_column(Text, nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False, index=True
    )

    # Relationships
    penerima = relationship(
        "Penerima",
        back_populates="fraud_logs",
        foreign_keys=[penerima_id],
    )

    def __repr__(self) -> str:
        return f"<FraudLog {self.fraud_type.value} score={self.similarity_score}>"
