"""Migrasi: buat tabel distribusi_harian + seed kategori Penerima Harian."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import Base, engine, SessionLocal
from app.models.distribusi_harian import DistribusiHarian  # noqa: F401 — ensure mapped
from app.models import Kategori
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def run():
    logger.info("Membuat tabel distribusi_harian (jika belum ada)...")
    Base.metadata.create_all(bind=engine)
    logger.info("Tabel OK")

    with SessionLocal() as db:
        exists = db.query(Kategori).filter(Kategori.nama == "Penerima Harian").first()
        if not exists:
            db.add(Kategori(
                nama="Penerima Harian",
                deskripsi="Penerima bantuan reguler harian (bulanan recurring)",
                weight=0.65,
                is_default=True,
                is_active=True,
            ))
            db.commit()
            logger.info("Kategori 'Penerima Harian' berhasil dibuat")
        else:
            logger.info("Kategori 'Penerima Harian' sudah ada — skip")

    logger.info("Migrasi selesai!")


if __name__ == "__main__":
    run()
