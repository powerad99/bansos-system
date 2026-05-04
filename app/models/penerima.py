"""Model Penerima Bantuan."""
import enum
from datetime import datetime, date

from sqlalchemy import Boolean, Date, DateTime, Enum as SAEnum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class PriorityLevel(str, enum.Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class PenerimaStatus(str, enum.Enum):
    MENUNGGU_DISTRIBUSI = "MENUNGGU_DISTRIBUSI"
    SUDAH_DISTRIBUSI = "SUDAH_DISTRIBUSI"


class Penerima(Base):
    __tablename__ = "penerima"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # Identitas
    nik: Mapped[str] = mapped_column(String(16), unique=True, nullable=False, index=True)
    nama: Mapped[str] = mapped_column(String(150), nullable=False, index=True)
    tempat_lahir: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tanggal_lahir: Mapped[date | None] = mapped_column(Date, nullable=True)
    jenis_kelamin: Mapped[str | None] = mapped_column(String(10), nullable=True)  # L / P
    alamat: Mapped[str] = mapped_column(Text, nullable=False)
    no_telp: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Kode seri otomatis berdasarkan kategori (e.g. FM-202604-00001)
    kode_seri: Mapped[str | None] = mapped_column(String(32), unique=True, nullable=True, index=True)

    # Status distribusi bantuan
    status_bantuan: Mapped[PenerimaStatus] = mapped_column(
        SAEnum(PenerimaStatus, name="penerima_status", create_type=False),
        default=PenerimaStatus.MENUNGGU_DISTRIBUSI,
        nullable=False,
    )

    # Petugas yang mendata
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Data sosioekonomi (untuk priority scoring)
    penghasilan: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    jumlah_tanggungan: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status_rumah: Mapped[str | None] = mapped_column(String(50), nullable=True)  # milik/sewa/menumpang

    # AI
    priority_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    priority_level: Mapped[PriorityLevel] = mapped_column(
        SAEnum(PriorityLevel, name="priority_level"),
        default=PriorityLevel.LOW,
        nullable=False,
    )

    # Anti-fraud
    fraud_flag: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    fraud_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relationships
    created_by = relationship("User", foreign_keys=[created_by_id])
    kategori_assoc = relationship(
        "PenerimaKategori",
        back_populates="penerima",
        cascade="all, delete-orphan",
    )
    distribusi_history = relationship(
        "Distribusi",
        back_populates="penerima",
        cascade="all, delete-orphan",
    )
    fraud_logs = relationship(
        "FraudLog",
        back_populates="penerima",
        cascade="all, delete-orphan",
        foreign_keys="FraudLog.penerima_id",
    )

    @property
    def kategori_list(self):
        """Helper: list kategori objects."""
        return [pk.kategori for pk in self.kategori_assoc]

    def __repr__(self) -> str:
        return f"<Penerima {self.nik} {self.nama} status={self.status_bantuan.value}>"
