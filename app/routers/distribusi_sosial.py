"""Router Distribusi Sosial.

Kategori: Fakir Miskin, Disabilitas, Anak Yatim Piatu.
  - 1 penerima hanya masuk 1 kategori (enforced di UI/service)
  - Data penerima cukup diinput 1x
  - Sistem auto-generate 12 bulan (Jan–Des) per tahun
  - Petugas hanya klik KONFIRMASI setiap bulan

Izin:
  Lihat list  : semua authenticated yang punya akses kategori sosial
  Konfirmasi  : punya task permission 'distribusi_sosial' + akses kategori
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
    require_manajemen,
    require_perm,
)
from app.models import Kategori, Penerima, PenerimaKategori, User
from app.models.distribusi_sosial import DistribusiSosial, StatusSosial
from app.schemas.distribusi_sosial import DistribusiSosialListResponse, DistribusiSosialOut
from app.services.distribusi_sosial_service import (
    generate_semua,
    generate_untuk_penerima,
    get_kategori_sosial_ids,
    konfirmasi,
    NAMA_KATEGORI_SOSIAL,
)
from app.services.export_service import export_distribusi_sosial_xlsx, export_filename

router = APIRouter(prefix="/distribusi-sosial", tags=["distribusi-sosial"])

require_distribusi_sosial = require_perm("distribusi_sosial")


# ── Dependency helpers ───────────────────────────────────────────────────────

def _require_akses_sosial(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    from app.models.user import UserRole as _Role
    if user.role in (_Role.ADMINISTRATOR, _Role.ADMIN):
        return user
    allowed = get_allowed_category_ids(user)
    if allowed is None:
        return user
    kat_ids = get_kategori_sosial_ids(db)
    if not set(kat_ids) & set(allowed):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Tidak punya akses ke kategori sosial",
        )
    return user


def _require_konfirmasi_sosial(
    user: User = Depends(require_distribusi_sosial),
    db: Session = Depends(get_db),
) -> User:
    from app.models.user import UserRole as _Role
    if user.role in (_Role.ADMINISTRATOR, _Role.ADMIN):
        return user
    allowed = get_allowed_category_ids(user)
    if allowed is None:
        return user
    kat_ids = get_kategori_sosial_ids(db)
    if not set(kat_ids) & set(allowed):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Tidak punya akses konfirmasi kategori sosial",
        )
    return user


# ── Base query ───────────────────────────────────────────────────────────────

def _base_query(db: Session, user: User):
    kat_ids = get_kategori_sosial_ids(db)

    q = (
        db.query(DistribusiSosial)
        .options(
            selectinload(DistribusiSosial.penerima),
            selectinload(DistribusiSosial.confirmed_by),
        )
        .join(Penerima, Penerima.id == DistribusiSosial.penerima_id)
        .join(PenerimaKategori, PenerimaKategori.penerima_id == DistribusiSosial.penerima_id)
        .filter(
            Penerima.is_active.is_(True),
            PenerimaKategori.kategori_id.in_(kat_ids),
        )
    )

    from app.models.user import UserRole as _Role
    if user.role not in (_Role.ADMINISTRATOR, _Role.ADMIN):
        allowed = get_allowed_category_ids(user)
        if allowed is not None:
            q = q.filter(PenerimaKategori.kategori_id.in_(allowed))

    return q


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("", response_model=DistribusiSosialListResponse)
def list_distribusi_sosial(
    bulan: Optional[int] = Query(None, ge=1, le=12),
    tahun: Optional[int] = Query(None),
    status_filter: Optional[StatusSosial] = Query(None, alias="status"),
    kategori_id: Optional[int] = Query(None, description="Filter berdasarkan kategori"),
    q: Optional[str] = Query(None, description="Cari nama / NIK / kode seri"),
    sort_by:  str = Query("created_at", pattern="^(created_at|nama)$"),
    sort_dir: str = Query("desc",       pattern="^(asc|desc)$"),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(_require_akses_sosial),
):
    query = _base_query(db, current_user)

    if bulan is not None:
        query = query.filter(DistribusiSosial.bulan == bulan)
    if tahun is not None:
        query = query.filter(DistribusiSosial.tahun == tahun)
    if status_filter is not None:
        query = query.filter(DistribusiSosial.status == status_filter)
    if kategori_id is not None:
        query = query.filter(PenerimaKategori.kategori_id == kategori_id)
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
def export_sosial_excel(
    bulan: Optional[int] = Query(None, ge=1, le=12),
    tahun: Optional[int] = Query(None),
    status_filter: Optional[StatusSosial] = Query(None, alias="status"),
    kategori_id: Optional[int] = Query(None),
    q: Optional[str] = Query(None, description="Cari nama / NIK / kode seri"),
    db: Session = Depends(get_db),
    current_user: User = Depends(_require_akses_sosial),
):
    query = _base_query(db, current_user)
    if bulan is not None:
        query = query.filter(DistribusiSosial.bulan == bulan)
    if tahun is not None:
        query = query.filter(DistribusiSosial.tahun == tahun)
    if status_filter is not None:
        query = query.filter(DistribusiSosial.status == status_filter)
    if kategori_id is not None:
        query = query.filter(PenerimaKategori.kategori_id == kategori_id)
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                Penerima.nama.ilike(like),
                Penerima.nik.ilike(like),
                Penerima.kode_seri.ilike(like),
            )
        )
    query = query.order_by(
        DistribusiSosial.tahun.desc(),
        DistribusiSosial.bulan.asc(),
        DistribusiSosial.penerima_id.asc(),
    )
    rows = query.all()
    blob = export_distribusi_sosial_xlsx(rows)
    fname = export_filename("distribusi_sosial")
    return Response(
        content=blob,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={fname}"},
    )


@router.post("/{dist_id}/konfirmasi", response_model=DistribusiSosialOut)
def konfirmasi_penerimaan(
    dist_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(_require_konfirmasi_sosial),
):
    try:
        dist = konfirmasi(db, dist_id, user.id)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))

    dist = (
        db.query(DistribusiSosial)
        .options(
            selectinload(DistribusiSosial.penerima),
            selectinload(DistribusiSosial.confirmed_by),
        )
        .filter(DistribusiSosial.id == dist_id)
        .first()
    )

    broadcast_sync("distribusi_sosial.konfirmasi", {
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
    """Generate 12 bulan distribusi untuk SEMUA penerima kategori sosial aktif. Hanya ADMIN."""
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
    tahun: int = Query(...),
    db: Session = Depends(get_db),
    _: User = Depends(require_manajemen),
):
    penerima = db.query(Penerima).filter(Penerima.id == penerima_id).first()
    if not penerima:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Penerima tidak ditemukan")
    created = generate_untuk_penerima(db, penerima_id, tahun)
    db.commit()
    return {"penerima_id": penerima_id, "tahun": tahun, "created": created}


@router.get("/ringkasan")
def ringkasan_sosial(
    tahun: int = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(_require_akses_sosial),
):
    from sqlalchemy import func, case
    from app.models.distribusi_sosial import StatusSosial as SS

    kat_ids = get_kategori_sosial_ids(db)
    rows = (
        db.query(
            DistribusiSosial.bulan,
            func.count(DistribusiSosial.id).label("total"),
            func.sum(
                case((DistribusiSosial.status == SS.SUDAH_DITERIMA, 1), else_=0)
            ).label("sudah"),
        )
        .join(Penerima, Penerima.id == DistribusiSosial.penerima_id)
        .join(PenerimaKategori, PenerimaKategori.penerima_id == DistribusiSosial.penerima_id)
        .filter(
            DistribusiSosial.tahun == tahun,
            Penerima.is_active.is_(True),
            PenerimaKategori.kategori_id.in_(kat_ids),
        )
        .group_by(DistribusiSosial.bulan)
        .order_by(DistribusiSosial.bulan)
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


@router.get("/kategori-sosial")
def get_kategori_sosial(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Kembalikan daftar kategori sosial beserta ID-nya."""
    rows = db.query(Kategori).filter(Kategori.nama.in_(NAMA_KATEGORI_SOSIAL)).all()
    return [{"id": k.id, "nama": k.nama} for k in rows]
