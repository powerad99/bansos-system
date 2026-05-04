"""Service untuk distribusi sosial otomatis (Fakir Miskin, Disabilitas, Anak Yatim Piatu)."""
from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Kategori, PenerimaKategori
from app.models.distribusi_sosial import DistribusiSosial, StatusSosial

logger = logging.getLogger(__name__)

NAMA_KATEGORI_SOSIAL = ["Fakir Miskin", "Disabilitas", "Anak Yatim Piatu"]


def get_kategori_sosial_ids(db: Session) -> list[int]:
    """Kembalikan list ID untuk 3 kategori sosial."""
    rows = db.query(Kategori.id).filter(Kategori.nama.in_(NAMA_KATEGORI_SOSIAL)).all()
    return [r.id for r in rows]


def generate_untuk_penerima(db: Session, penerima_id: int, tahun: int) -> int:
    """Generate 12 entri Jan–Des untuk satu penerima.

    Idempoten: bulan yang sudah ada dilewati. Return jumlah baris baru.
    Caller wajib commit setelah memanggil fungsi ini.
    """
    existing_bulan = {
        row.bulan
        for row in db.query(DistribusiSosial.bulan).filter(
            DistribusiSosial.penerima_id == penerima_id,
            DistribusiSosial.tahun == tahun,
        ).all()
    }
    count = 0
    for bulan in range(1, 13):
        if bulan in existing_bulan:
            continue
        db.add(DistribusiSosial(
            penerima_id=penerima_id,
            bulan=bulan,
            tahun=tahun,
            status=StatusSosial.BELUM_DITERIMA,
        ))
        count += 1
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        logger.warning(
            "IntegrityError generate distribusi sosial penerima_id=%d tahun=%d",
            penerima_id, tahun,
        )
        count = 0
    return count


def generate_semua(db: Session, tahun: int) -> dict:
    """Generate distribusi sosial untuk SEMUA penerima aktif berkategori sosial.

    Idempoten — aman dipanggil berkali-kali. Return ringkasan operasi.
    """
    kat_ids = get_kategori_sosial_ids(db)
    if not kat_ids:
        return {"penerima_count": 0, "created": 0}

    penerima_ids = list({
        row.penerima_id
        for row in db.query(PenerimaKategori.penerima_id)
        .filter(PenerimaKategori.kategori_id.in_(kat_ids))
        .all()
    })

    total = 0
    for pid in penerima_ids:
        total += generate_untuk_penerima(db, pid, tahun)
    db.commit()
    logger.info(
        "generate_semua sosial tahun=%d: %d penerima, %d baris baru",
        tahun, len(penerima_ids), total,
    )
    return {"penerima_count": len(penerima_ids), "created": total}


def konfirmasi(db: Session, dist_id: int, petugas_id: int) -> DistribusiSosial:
    """Konfirmasi satu entri distribusi sosial. Raise ValueError jika sudah dikonfirmasi."""
    dist = db.query(DistribusiSosial).filter(DistribusiSosial.id == dist_id).first()
    if not dist:
        raise ValueError("Distribusi tidak ditemukan")
    if dist.status == StatusSosial.SUDAH_DITERIMA:
        raise ValueError("Distribusi ini sudah dikonfirmasi sebelumnya — tidak bisa dikonfirmasi 2x")
    dist.status = StatusSosial.SUDAH_DITERIMA
    dist.confirmed_by_id = petugas_id
    dist.confirmed_at = datetime.utcnow()
    db.commit()
    db.refresh(dist)
    return dist
