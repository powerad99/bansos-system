"""Seed data wajib.

Kategori default (TIDAK BOLEH DIHAPUS, ditandai is_default=True):
  1. Penerima Bulanan  (weight 0.7)
  2. Fakir Miskin      (weight 1.0)
  3. Anak Yatim Piatu  (weight 0.85)
  4. Disabilitas       (weight 0.9)

Plus: 1 admin user default (kalau belum ada).
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models import Kategori, User, UserRole
from app.models.permission import Permission

logger = logging.getLogger(__name__)


DEFAULT_KATEGORI = [
    {
        "nama": "Penerima Bulanan",
        "deskripsi": "Penerima bantuan reguler bulanan",
        "weight": 0.7,
    },
    {
        "nama": "Fakir Miskin",
        "deskripsi": "Keluarga miskin / pra-sejahtera",
        "weight": 1.0,
    },
    {
        "nama": "Anak Yatim Piatu",
        "deskripsi": "Anak yatim, piatu, atau yatim-piatu",
        "weight": 0.85,
    },
    {
        "nama": "Disabilitas",
        "deskripsi": "Penyandang disabilitas fisik / mental",
        "weight": 0.9,
    },
]


def seed_kategori(db: Session) -> int:
    """Insert kategori default kalau belum ada. Return jumlah baru."""
    inserted = 0
    for k in DEFAULT_KATEGORI:
        exists = db.query(Kategori).filter(Kategori.nama == k["nama"]).first()
        if exists:
            # Pastikan tetap is_default=True meski sudah ada (lock)
            if not exists.is_default:
                exists.is_default = True
                db.add(exists)
            continue
        db.add(Kategori(**k, is_default=True, is_active=True))
        inserted += 1
    db.commit()
    logger.info("Seed kategori: %d new (total target=%d)", inserted, len(DEFAULT_KATEGORI))
    return inserted


def seed_admin(
    db: Session,
    *,
    username: str = "admin",
    password: str = "admin123",
    full_name: str = "Administrator",
) -> bool:
    """Buat admin user default kalau belum ada. Return True kalau dibuat baru."""
    if db.query(User).filter(User.username == username).first():
        return False
    user = User(
        username=username,
        full_name=full_name,
        email=f"{username}@bansos.local",
        password_hash=hash_password(password),
        role=UserRole.ADMINISTRATOR,
        is_active=True,
    )
    db.add(user)
    db.commit()
    logger.warning(
        "Admin default dibuat: username=%s password=%s -- GANTI DI PRODUKSI!",
        username, password,
    )
    return True


DEFAULT_PERMISSIONS = [
    {"name": "entri_penerima",     "label": "Menu Pendaftaran (entri & edit penerima)"},
    {"name": "distribusi",         "label": "Distribusi via Scan QR"},
    {"name": "pendataan_bulanan",  "label": "Menu Pendataan Bulanan"},
    {"name": "distribusi_bulanan", "label": "Menu Distribusi Bulanan (konfirmasi 12 bulan)"},
    {"name": "distribusi_sosial",  "label": "Menu Distribusi (Fakir Miskin, Disabilitas, Yatim Piatu)"},
    {"name": "laporan_distribusi", "label": "Menu Laporan (Harian & Bulanan)"},
    {"name": "database_bip",       "label": "Menu Database BIP"},
]


def seed_permissions(db: Session) -> int:
    """Seed 5 task permissions. Idempotent — skip yang sudah ada."""
    inserted = 0
    for p in DEFAULT_PERMISSIONS:
        exists = db.query(Permission).filter(Permission.name == p["name"]).first()
        if not exists:
            db.add(Permission(**p))
            inserted += 1
        elif exists.label != p["label"]:
            exists.label = p["label"]
    db.commit()
    logger.info("Seed permissions: %d new (total=%d)", inserted, len(DEFAULT_PERMISSIONS))
    return inserted


def run_all_seeds(db: Session) -> None:
    seed_kategori(db)
    seed_admin(db)
    seed_permissions(db)
