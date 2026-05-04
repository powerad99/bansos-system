"""Router Distribusi Bulanan.

Kategori 'Penerima Bulanan':
  - Data penerima cukup diinput 1x
  - Sistem auto-generate 12 bulan (Jan–Des) per tahun
  - Petugas hanya klik KONFIRMASI setiap bulan
  - Semua aktivitas tercatat (confirmed_by, confirmed_at)

Izin:
  Lihat list  : semua authenticated yang punya akses kategori Bulanan
  Konfirmasi  : punya task permission 'distribusi_bulanan' + akses kategori Bulanan
  Generate    : Administrator / Admin saja
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import or_
from sqlalchemy.orm import Session, selectinload

from app.core.ws_manager import broadcast_sync
from app.database import get_db
from app.dependencies import (
    get_allowed_category_ids,
    get_current_user,
    require_distribusi_bulanan,
    require_manajemen,
)
from app.models import Kategori, Penerima, PenerimaKategori, User
from app.models.distribusi_bulanan import DistribusiBulanan, StatusBulanan
from app.schemas.distribusi_bulanan import DistribusiBulananListResponse, DistribusiBulananOut
from app.services.distribusi_bulanan_service import (
    generate_semua,
    generate_untuk_penerima,
    get_kategori_bulanan_id,
    konfirmasi,
)
from app.services.export_service import export_distribusi_bulanan_xlsx, export_filename

router = APIRouter(prefix="/distribusi-bulanan", tags=["distribusi-bulanan"])


# ── Dependency: akses kategori Penerima Bulanan ──────────────────────────────

def _require_akses_bulanan(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    """User harus punya akses ke kategori 'Penerima Bulanan'."""
    from app.models.user import UserRole as _Role
    if user.role in (_Role.ADMINISTRATOR, _Role.ADMIN):
        return user
    allowed = get_allowed_category_ids(user)
    if allowed is None:
        return user
    kat_id = get_kategori_bulanan_id(db)
    if kat_id is None or kat_id not in allowed:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Tidak punya akses ke kategori Penerima Bulanan",
        )
    return user


def _require_konfirmasi_bulanan(
    user: User = Depends(require_distribusi_bulanan),
    db: Session = Depends(get_db),
) -> User:
    """Task permission distribusi_bulanan + akses kategori Bulanan."""
    from app.models.user import UserRole as _Role
    if user.role in (_Role.ADMINISTRATOR, _Role.ADMIN):
        return user
    allowed = get_allowed_category_ids(user)
    if allowed is None:
        return user
    kat_id = get_kategori_bulanan_id(db)
    if kat_id is None or kat_id not in allowed:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Tidak punya akses konfirmasi kategori Penerima Bulanan",
        )
    return user


# ── Base query helper ────────────────────────────────────────────────────────

def _base_query(db: Session, user: User):
    """Query distribusi_bulanan hanya untuk penerima Kategori Bulanan aktif."""
    kat_id = get_kategori_bulanan_id(db)

    q = (
        db.query(DistribusiBulanan)
        .options(
            selectinload(DistribusiBulanan.penerima),
            selectinload(DistribusiBulanan.confirmed_by),
        )
        .join(Penerima, Penerima.id == DistribusiBulanan.penerima_id)
        .join(PenerimaKategori, PenerimaKategori.penerima_id == DistribusiBulanan.penerima_id)
        .filter(
            Penerima.is_active.is_(True),
            PenerimaKategori.kategori_id == kat_id,
        )
    )

    # Batasi lebih lanjut berdasarkan kategori yang diizinkan user
    from app.models.user import UserRole as _Role
    if user.role not in (_Role.ADMINISTRATOR, _Role.ADMIN):
        allowed = get_allowed_category_ids(user)
        if allowed is not None:
            q = q.filter(PenerimaKategori.kategori_id.in_(allowed))

    return q


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("", response_model=DistribusiBulananListResponse)
def list_distribusi_bulanan(
    bulan: Optional[int] = Query(None, ge=1, le=12, description="Filter bulan 1–12"),
    tahun: Optional[int] = Query(None, description="Filter tahun, misal 2025"),
    status_filter: Optional[StatusBulanan] = Query(None, alias="status"),
    q: Optional[str] = Query(None, description="Cari nama / NIK / kode seri"),
    sort_by:  str = Query("created_at", pattern="^(created_at|nama)$"),
    sort_dir: str = Query("desc",       pattern="^(asc|desc)$"),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(_require_akses_bulanan),
):
    """List distribusi bulanan dengan filter bulan, tahun, status, dan pencarian."""
    query = _base_query(db, current_user)

    if bulan is not None:
        query = query.filter(DistribusiBulanan.bulan == bulan)
    if tahun is not None:
        query = query.filter(DistribusiBulanan.tahun == tahun)
    if status_filter is not None:
        query = query.filter(DistribusiBulanan.status == status_filter)
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                Penerima.nama.ilike(like),
                Penerima.nik.ilike(like),
                Penerima.kode_seri.ilike(like),
            )
        )

    sort_col = Penerima.nama if sort_by == "nama" else Penerima.created_at
    query = query.order_by(
        sort_col.asc() if sort_dir == "asc" else sort_col.desc()
    )
    total = query.count()
    items = query.offset((page - 1) * size).limit(size).all()
    return {"total": total, "page": page, "size": size, "items": items}


@router.get("/export/xlsx")
def export_distribusi_bulanan_excel(
    bulan: Optional[int] = Query(None, ge=1, le=12),
    tahun: Optional[int] = Query(None),
    status_filter: Optional[StatusBulanan] = Query(None, alias="status"),
    db: Session = Depends(get_db),
    current_user: User = Depends(_require_akses_bulanan),
):
    """Export distribusi bulanan ke Excel."""
    query = (
        _base_query(db, current_user)
        .options(
            selectinload(DistribusiBulanan.penerima),
            selectinload(DistribusiBulanan.confirmed_by),
        )
    )
    if bulan is not None:
        query = query.filter(DistribusiBulanan.bulan == bulan)
    if tahun is not None:
        query = query.filter(DistribusiBulanan.tahun == tahun)
    if status_filter is not None:
        query = query.filter(DistribusiBulanan.status == status_filter)
    query = query.order_by(
        DistribusiBulanan.tahun.desc(),
        DistribusiBulanan.bulan.asc(),
        DistribusiBulanan.penerima_id.asc(),
    )
    rows = query.all()
    blob = export_distribusi_bulanan_xlsx(rows)
    fname = export_filename("distribusi_bulanan")
    return Response(
        content=blob,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={fname}"},
    )


@router.post("/{dist_id}/konfirmasi", response_model=DistribusiBulananOut)
def konfirmasi_penerimaan(
    dist_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(_require_konfirmasi_bulanan),
):
    """Konfirmasi penerimaan bantuan bulanan. Tidak bisa dikonfirmasi 2x."""
    try:
        dist = konfirmasi(db, dist_id, user.id)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))

    # Reload dengan relasi untuk response lengkap
    dist = (
        db.query(DistribusiBulanan)
        .options(
            selectinload(DistribusiBulanan.penerima),
            selectinload(DistribusiBulanan.confirmed_by),
        )
        .filter(DistribusiBulanan.id == dist_id)
        .first()
    )

    broadcast_sync("distribusi_bulanan.konfirmasi", {
        "id": dist.id,
        "penerima_id": dist.penerima_id,
        "bulan": dist.bulan,
        "tahun": dist.tahun,
        "petugas": user.full_name,
    })
    return dist


@router.post("/generate", status_code=status.HTTP_200_OK)
def generate_distribusi(
    tahun: int = Query(..., description="Tahun yang di-generate, misal 2025"),
    db: Session = Depends(get_db),
    _: User = Depends(require_manajemen),
):
    """Generate 12 bulan distribusi untuk SEMUA penerima Bulanan aktif.

    Hanya ADMIN. Idempoten — aman dipanggil berulang kali.
    """
    result = generate_semua(db, tahun)
    return {
        "tahun": tahun,
        "penerima_count": result["penerima_count"],
        "created": result["created"],
        "message": f"Generate selesai: {result['created']} entri baru untuk {result['penerima_count']} penerima",
    }


@router.post("/generate/{penerima_id}", status_code=status.HTTP_200_OK)
def generate_untuk_satu_penerima(
    penerima_id: int,
    tahun: int = Query(..., description="Tahun yang di-generate"),
    db: Session = Depends(get_db),
    _: User = Depends(require_manajemen),
):
    """Generate 12 bulan distribusi untuk satu penerima tertentu. Hanya ADMIN."""
    penerima = db.query(Penerima).filter(Penerima.id == penerima_id).first()
    if not penerima:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Penerima tidak ditemukan")
    created = generate_untuk_penerima(db, penerima_id, tahun)
    db.commit()
    return {
        "penerima_id": penerima_id,
        "tahun": tahun,
        "created": created,
        "message": f"{created} entri baru dibuat",
    }


@router.get("/ringkasan", summary="Ringkasan per bulan")
def ringkasan_bulanan(
    tahun: int = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(_require_akses_bulanan),
):
    """Ringkasan total & sudah dikonfirmasi per bulan untuk satu tahun."""
    from sqlalchemy import func, case
    from app.models.distribusi_bulanan import StatusBulanan as SB

    kat_id = get_kategori_bulanan_id(db)
    rows = (
        db.query(
            DistribusiBulanan.bulan,
            func.count(DistribusiBulanan.id).label("total"),
            func.sum(
                case((DistribusiBulanan.status == SB.SUDAH_DITERIMA, 1), else_=0)
            ).label("sudah"),
        )
        .join(Penerima, Penerima.id == DistribusiBulanan.penerima_id)
        .join(PenerimaKategori, PenerimaKategori.penerima_id == DistribusiBulanan.penerima_id)
        .filter(
            DistribusiBulanan.tahun == tahun,
            Penerima.is_active.is_(True),
            PenerimaKategori.kategori_id == kat_id,
        )
        .group_by(DistribusiBulanan.bulan)
        .order_by(DistribusiBulanan.bulan)
        .all()
    )

    _NAMA = ["", "Januari", "Februari", "Maret", "April", "Mei", "Juni",
             "Juli", "Agustus", "September", "Oktober", "November", "Desember"]
    return [
        {
            "bulan": r.bulan,
            "nama_bulan": _NAMA[r.bulan],
            "total": r.total,
            "sudah": int(r.sudah or 0),
            "belum": r.total - int(r.sudah or 0),
        }
        for r in rows
    ]
