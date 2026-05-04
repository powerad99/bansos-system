"""Database BIP — tampilan lengkap penerima bantuan dari semua kategori BIP.

GET /database-bip/              paginated list + filter
GET /database-bip/ringkasan     summary per kategori & statistik
GET /database-bip/export/xlsx   export Excel
GET /database-bip/{id}          detail + riwayat distribusi
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.dependencies import get_allowed_category_ids, require_perm
from app.models import Distribusi, Kategori, Penerima, PenerimaKategori, User
from app.models.penerima import PenerimaStatus, PriorityLevel
from app.services.export_service import export_filename, export_penerima_xlsx

router = APIRouter(prefix="/database-bip", tags=["database-bip"])
require_db_bip = require_perm("database_bip")

BIP_KATEGORI_NAMES = ["Penerima Bulanan", "Fakir Miskin", "Anak Yatim Piatu", "Disabilitas"]


def _get_bip_ids(db: Session) -> list[int]:
    return [
        r.id for r in
        db.query(Kategori.id).filter(Kategori.nama.in_(BIP_KATEGORI_NAMES)).all()
    ]


def _restrict(bip_ids: list[int], allowed: list[int] | None) -> list[int]:
    if allowed is None:
        return bip_ids
    return [i for i in bip_ids if i in allowed]


def _fetch_q(db: Session, bip_ids: list[int]):
    """Query penerima aktif yang ada di ≥1 kategori BIP, eager-load kategori."""
    return (
        db.query(Penerima)
        .options(selectinload(Penerima.kategori_assoc).selectinload(PenerimaKategori.kategori))
        .join(PenerimaKategori, PenerimaKategori.penerima_id == Penerima.id)
        .filter(PenerimaKategori.kategori_id.in_(bip_ids), Penerima.is_active.is_(True))
        .distinct()
    )


def _pids_q(db: Session, bip_ids: list[int]):
    """Subquery: distinct penerima IDs in BIP categories (untuk counting)."""
    return (
        db.query(Penerima.id)
        .join(PenerimaKategori, PenerimaKategori.penerima_id == Penerima.id)
        .filter(PenerimaKategori.kategori_id.in_(bip_ids), Penerima.is_active.is_(True))
        .distinct()
    )


def _to_dict(p: Penerima) -> Dict[str, Any]:
    return {
        "id":               p.id,
        "kode_seri":        p.kode_seri or "-",
        "nik":              p.nik,
        "nama":             p.nama,
        "tempat_lahir":     p.tempat_lahir or "-",
        "tanggal_lahir":    p.tanggal_lahir.isoformat() if p.tanggal_lahir else "-",
        "jenis_kelamin":    p.jenis_kelamin or "-",
        "alamat":           p.alamat,
        "no_telp":          p.no_telp or "-",
        "penghasilan":      p.penghasilan,
        "jumlah_tanggungan": p.jumlah_tanggungan,
        "status_rumah":     p.status_rumah or "-",
        "priority_score":   round(p.priority_score, 4),
        "priority_level":   p.priority_level.value,
        "fraud_flag":       p.fraud_flag,
        "fraud_reason":     p.fraud_reason or "",
        "status_bantuan":   p.status_bantuan.value,
        "is_active":        p.is_active,
        "created_at":       p.created_at.strftime("%Y-%m-%d %H:%M"),
        "updated_at":       p.updated_at.strftime("%Y-%m-%d %H:%M"),
        "kategori": [
            {"id": pk.kategori.id, "nama": pk.kategori.nama}
            for pk in p.kategori_assoc if pk.kategori
        ],
    }


# ── Ringkasan ─────────────────────────────────────────────────────────────────

@router.get("/ringkasan")
def ringkasan(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_db_bip),
) -> Dict[str, Any]:
    bip_ids = _restrict(_get_bip_ids(db), get_allowed_category_ids(current_user))
    empty = {
        "total": 0, "per_kategori": [],
        "sudah_distribusi": 0, "menunggu_distribusi": 0,
        "fraud_count": 0,
        "priority_high": 0, "priority_medium": 0, "priority_low": 0,
    }
    if not bip_ids:
        return empty

    pids = _pids_q(db, bip_ids)

    def cnt(**eq) -> int:
        q = db.query(func.count(Penerima.id)).filter(Penerima.id.in_(pids))
        for col, val in eq.items():
            q = q.filter(getattr(Penerima, col) == val)
        return q.scalar() or 0

    def cnt_bool(col: str, val: bool) -> int:
        return (
            db.query(func.count(Penerima.id))
            .filter(Penerima.id.in_(pids), getattr(Penerima, col).is_(val))
            .scalar() or 0
        )

    total = db.query(func.count()).select_from(pids.subquery()).scalar() or 0

    kat_rows = (
        db.query(Kategori.nama, func.count(PenerimaKategori.penerima_id).label("jumlah"))
        .join(PenerimaKategori, PenerimaKategori.kategori_id == Kategori.id)
        .join(Penerima, Penerima.id == PenerimaKategori.penerima_id)
        .filter(Kategori.id.in_(bip_ids), Penerima.is_active.is_(True))
        .group_by(Kategori.id, Kategori.nama)
        .all()
    )

    return {
        "total":              total,
        "per_kategori":       [{"nama": r.nama, "jumlah": int(r.jumlah)} for r in kat_rows],
        "sudah_distribusi":   cnt(status_bantuan=PenerimaStatus.SUDAH_DISTRIBUSI),
        "menunggu_distribusi": cnt(status_bantuan=PenerimaStatus.MENUNGGU_DISTRIBUSI),
        "fraud_count":        cnt_bool("fraud_flag", True),
        "priority_high":      cnt(priority_level=PriorityLevel.HIGH),
        "priority_medium":    cnt(priority_level=PriorityLevel.MEDIUM),
        "priority_low":       cnt(priority_level=PriorityLevel.LOW),
    }


# ── List ──────────────────────────────────────────────────────────────────────

@router.get("")
def list_bip(
    page:          int               = Query(1,  ge=1),
    size:          int               = Query(25, ge=1, le=200),
    q:             Optional[str]     = Query(None, description="NIK / Nama / Kode Seri / Alamat"),
    kategori_id:   Optional[int]     = Query(None),
    priority:      Optional[PriorityLevel]    = Query(None),
    status_bantuan: Optional[PenerimaStatus]  = Query(None),
    fraud_only:    bool              = Query(False),
    sort_by:       str               = Query("created_at", pattern="^(priority_score|created_at|nama)$"),
    sort_dir:      str               = Query("desc", pattern="^(asc|desc)$"),
    db:            Session           = Depends(get_db),
    current_user:  User              = Depends(require_db_bip),
) -> Dict[str, Any]:
    bip_ids = _restrict(_get_bip_ids(db), get_allowed_category_ids(current_user))
    if not bip_ids:
        return {"total": 0, "page": page, "size": size, "items": []}

    query = _fetch_q(db, bip_ids)

    if kategori_id is not None and kategori_id in bip_ids:
        query = query.filter(PenerimaKategori.kategori_id == kategori_id)

    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                Penerima.nama.ilike(like),
                Penerima.nik.ilike(like),
                Penerima.kode_seri.ilike(like),
                Penerima.alamat.ilike(like),
            )
        )
    if priority is not None:
        query = query.filter(Penerima.priority_level == priority)
    if status_bantuan is not None:
        query = query.filter(Penerima.status_bantuan == status_bantuan)
    if fraud_only:
        query = query.filter(Penerima.fraud_flag.is_(True))

    sort_col = {
        "priority_score": Penerima.priority_score,
        "created_at":     Penerima.created_at,
        "nama":           Penerima.nama,
    }[sort_by]
    query = query.order_by(sort_col.desc() if sort_dir == "desc" else sort_col.asc())

    total = query.count()
    rows  = query.offset((page - 1) * size).limit(size).all()
    return {"total": total, "page": page, "size": size, "items": [_to_dict(p) for p in rows]}


# ── Export ────────────────────────────────────────────────────────────────────

@router.get("/export/xlsx")
def export_bip(
    kategori_id:   Optional[int]     = Query(None),
    priority:      Optional[PriorityLevel]    = Query(None),
    fraud_only:    bool              = Query(False),
    db:            Session           = Depends(get_db),
    current_user:  User              = Depends(require_db_bip),
):
    bip_ids = _restrict(_get_bip_ids(db), get_allowed_category_ids(current_user))
    if not bip_ids:
        bip_ids = [-1]

    query = _fetch_q(db, bip_ids)
    if kategori_id is not None and kategori_id in bip_ids:
        query = query.filter(PenerimaKategori.kategori_id == kategori_id)
    if priority is not None:
        query = query.filter(Penerima.priority_level == priority)
    if fraud_only:
        query = query.filter(Penerima.fraud_flag.is_(True))
    query = query.order_by(Penerima.priority_score.desc())

    rows = query.all()
    blob = export_penerima_xlsx(rows)
    fname = export_filename("database_bip")
    return Response(
        content=blob,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={fname}"},
    )


# ── Detail ────────────────────────────────────────────────────────────────────

@router.get("/{penerima_id}")
def detail_bip(
    penerima_id: int,
    db:          Session = Depends(get_db),
    current_user: User   = Depends(require_db_bip),
) -> Dict[str, Any]:
    bip_ids = _restrict(_get_bip_ids(db), get_allowed_category_ids(current_user))

    p = (
        db.query(Penerima)
        .options(selectinload(Penerima.kategori_assoc).selectinload(PenerimaKategori.kategori))
        .filter(Penerima.id == penerima_id)
        .first()
    )
    if not p:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Penerima tidak ditemukan")

    p_kat_ids = [pk.kategori_id for pk in p.kategori_assoc]
    if not any(kid in bip_ids for kid in p_kat_ids):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Tidak ada akses ke data ini")

    # Last 10 distribusi
    riwayat = (
        db.query(Distribusi)
        .filter(Distribusi.penerima_id == penerima_id)
        .order_by(Distribusi.tanggal_distribusi.desc())
        .limit(10)
        .all()
    )

    result = _to_dict(p)
    result["riwayat_distribusi"] = [
        {
            "no_seri":      d.no_seri or "-",
            "jenis_bantuan": d.jenis_bantuan or "-",
            "nominal":      d.nominal or 0,
            "status":       d.status.value,
            "tanggal":      d.tanggal_distribusi.strftime("%Y-%m-%d %H:%M"),
        }
        for d in riwayat
    ]
    return result
