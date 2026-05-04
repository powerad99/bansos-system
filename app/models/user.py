"""Model User — 3 tingkatan: Administrator, Admin, Petugas."""
import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum as SAEnum, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class UserRole(str, enum.Enum):
    ADMINISTRATOR = "administrator"   # superadmin: bisa buat & kelola user
    ADMIN         = "admin"           # manajemen: lihat semua data & laporan
    PETUGAS       = "petugas"         # lapangan: dibatasi task & kategori


ROLE_LABEL: dict[UserRole, str] = {
    UserRole.ADMINISTRATOR: "Administrator",
    UserRole.ADMIN:         "Admin",
    UserRole.PETUGAS:       "Petugas",
}


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(128), nullable=False)
    email: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True)
    no_telp: Mapped[str | None] = mapped_column(String(20), nullable=True)
    keterangan: Mapped[str | None] = mapped_column(Text, nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        SAEnum(UserRole, name="user_role", values_callable=lambda x: [e.value for e in x]),
        default=UserRole.PETUGAS,
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Relationships
    distribusi_dilakukan = relationship("Distribusi", back_populates="petugas")
    user_permissions: Mapped[list["UserPermission"]] = relationship(  # type: ignore
        "UserPermission", back_populates="user", cascade="all, delete-orphan"
    )
    user_categories: Mapped[list["UserCategory"]] = relationship(  # type: ignore
        "UserCategory", back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<User {self.username} ({self.role.value})>"
