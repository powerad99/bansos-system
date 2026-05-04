"""Service untuk distribusi bulanan otomatis (kategori Penerima Bulanan)."""
from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Kategori, PenerimaKategori
from app.models.distribusi_bulanan import DistribusiBulanan, StatusBulanan

logger = logging.getLogger(__name__)

NAMA_KATEGORI_BULANAN = "Penerima Bulanan"


def get_kategori_bulanan_id(db: Session) -> int | None:
    k = db.query(Kategori).filter(Kategori.nama == NAMA_KATEGORI_BULANAN).first()
    return k.id if k else None


def generate_untuk_penerima(db: Session, penerima_id: int, tahun: int) -> int:
    """Generate 12 entri Jan–Des untuk satu penerima.

    Idempoten: bulan yang sudah ada dilewati. Return jumlah baris baru.
    Caller wajib commit setelah memanggil fungsi ini.
    """
    existing_bulan = {
        row.bulan
        for row in db.query(DistribusiBulanan.bulan).filter(
            DistribusiBulanan.penerima_id == penerima_id,
            DistribusiBulanan.tahun == tahun,
        ).all()
    }
    count = 0
    for bulan in range(1, 13):
        if bulan in existing_bulan:
            continue
        db.add(DistribusiBulanan(
            penerima_id=penerima_id,
            bulan=bulan,
            tahun=tahun,
            status=StatusBulanan.BELUM_DITERIMA,
        ))
        count += 1
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        logger.warning(
            "IntegrityError generate distribusi bulanan penerima_id=%d tahun=%d",
            penerima_id, tahun,
        )
        count = 0
    return count


def generate_semua(db: Session, tahun: int) -> dict:
    """Generate distribusi bulanan untuk SEMUA penerima aktif berkategori Bulanan.

    Idempoten — aman dipanggil berkali-kali. Return ringkasan operasi.
    """
    kat_id = get_kategori_bulanan_id(db)
    if not kat_id:
        return {"penerima_count": 0, "created": 0}

    penerima_ids = [
        row.penerima_id
        for row in db.query(PenerimaKategori.penerima_id)
        .filter(PenerimaKategori.kategori_id == kat_id)
        .all()
    ]

    total = 0
    for pid in penerima_ids:
        total += generate_untuk_penerima(db, pid, tahun)
    db.commit()
    logger.info(
        "generate_semua tahun=%d: %d penerima, %d baris baru",
        tahun, len(penerima_ids), total,
    )
    return {"penerima_count": len(penerima_ids), "created": total}


def konfirmasi(db: Session, dist_id: int, petugas_id: int) -> DistribusiBulanan:
    """Konfirmasi satu entri distribusi bulanan. Raise ValueError jika sudah dikonfirmasi."""
    dist = db.query(DistribusiBulanan).filter(DistribusiBulanan.id == dist_id).first()
    if not dist:
        raise ValueError("Distribusi bulanan tidak ditemukan")
    if dist.status == StatusBulanan.SUDAH_DITERIMA:
        raise ValueError("Distribusi ini sudah dikonfirmasi sebelumnya — tidak bisa dikonfirmasi 2x")
    dist.status = StatusBulanan.SUDAH_DITERIMA
    dist.confirmed_by_id = petugas_id
    dist.confirmed_at = datetime.utcnow()
    db.commit()
    db.refresh(dist)
    return dist
