"""Statistik endpoints — dipakai dashboard & laporan manajemen."""
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user, require_manajemen
from app.models import (
    Distribusi,
    DistribusiStatus,
    FraudLog,
    Kategori,
    Penerima,
    PenerimaKategori,
    PriorityLevel,
    User,
    UserRole,
)

router = APIRouter(prefix="/statistik", tags=["statistik"])


@router.get("", summary="Overview dashboard")
def overview(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> Dict[str, Any]:
    total_penerima = db.query(func.count(Penerima.id)).scalar() or 0
    total_aktif = (
        db.query(func.count(Penerima.id)).filter(Penerima.is_active.is_(True)).scalar() or 0
    )
    total_fraud = (
        db.query(func.count(Penerima.id)).filter(Penerima.fraud_flag.is_(True)).scalar() or 0
    )

    priority_rows = (
        db.query(Penerima.priority_level, func.count(Penerima.id))
        .group_by(Penerima.priority_level)
        .all()
    )
    per_priority = {lvl.value: 0 for lvl in PriorityLevel}
    for lvl, cnt in priority_rows:
        per_priority[lvl.value] = cnt

    kategori_rows = (
        db.query(Kategori.nama, func.count(PenerimaKategori.penerima_id))
        .outerjoin(PenerimaKategori, PenerimaKategori.kategori_id == Kategori.id)
        .group_by(Kategori.id, Kategori.nama)
        .order_by(Kategori.weight.desc())
        .all()
    )
    per_kategori = [{"nama": n, "jumlah": int(c)} for n, c in kategori_rows]

    total_distribusi = db.query(func.count(Distribusi.id)).scalar() or 0
    distribusi_rows = (
        db.query(Distribusi.status, func.count(Distribusi.id))
        .group_by(Distribusi.status)
        .all()
    )
    per_status = {s.value: 0 for s in DistribusiStatus}
    for s, c in distribusi_rows:
        per_status[s.value] = c

    cutoff = datetime.utcnow() - timedelta(days=7)
    distribusi_week = (
        db.query(func.count(Distribusi.id))
        .filter(Distribusi.tanggal_distribusi >= cutoff)
        .scalar() or 0
    )
    total_fraud_logs = db.query(func.count(FraudLog.id)).scalar() or 0

    return {
        "penerima": {
            "total": total_penerima,
            "aktif": total_aktif,
            "fraud_flagged": total_fraud,
            "per_priority": per_priority,
            "per_kategori": per_kategori,
        },
        "distribusi": {
            "total": total_distribusi,
            "per_status": per_status,
            "last_7_days": distribusi_week,
        },
        "fraud_logs": {"total": total_fraud_logs},
    }


@router.get("/petugas", summary="Rekap kinerja setiap petugas distribusi")
def statistik_petugas(
    hari: int = Query(30, ge=1, le=365, description="Rentang hari ke belakang"),
    db: Session = Depends(get_db),
    _: User = Depends(require_manajemen),
) -> Dict[str, Any]:
    """Rekap distribusi per petugas — untuk Admin & Supervisor."""
    cutoff = datetime.utcnow() - timedelta(days=hari)

    rows = (
        db.query(
            User.id,
            User.username,
            User.full_name,
            User.role,
            func.count(Distribusi.id).label("total_distribusi"),
            func.sum(
                case((Distribusi.status == DistribusiStatus.DISTRIBUTED, 1), else_=0)
            ).label("distributed"),
            func.sum(
                case((Distribusi.status == DistribusiStatus.REJECTED, 1), else_=0)
            ).label("rejected"),
            func.coalesce(func.sum(Distribusi.nominal), 0).label("total_nominal"),
        )
        .outerjoin(
            Distribusi,
            (Distribusi.petugas_id == User.id)
            & (Distribusi.tanggal_distribusi >= cutoff),
        )
        .filter(
            User.is_active.is_(True),
            User.role.in_([UserRole.PETUGAS, UserRole.ADMIN, UserRole.ADMINISTRATOR]),
        )
        .group_by(User.id, User.username, User.full_name, User.role)
        .order_by(func.count(Distribusi.id).desc())
        .all()
    )

    return {
        "periode_hari": hari,
        "sejak": cutoff.strftime("%Y-%m-%d"),
        "petugas": [
            {
                "id": r.id,
                "username": r.username,
                "full_name": r.full_name,
                "role": r.role.value,
                "total_distribusi": r.total_distribusi or 0,
                "distributed": int(r.distributed or 0),
                "rejected": int(r.rejected or 0),
                "total_nominal": float(r.total_nominal or 0),
            }
            for r in rows
        ],
    }


@router.get("/petugas/me", summary="Rekap kinerja sendiri")
def statistik_saya(
    hari: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Setiap user bisa lihat rekap distribusi yang dia kerjakan."""
    cutoff = datetime.utcnow() - timedelta(days=hari)

    q = (
        db.query(Distribusi)
        .filter(
            Distribusi.petugas_id == current_user.id,
            Distribusi.tanggal_distribusi >= cutoff,
        )
    )
    total = q.count()
    distributed = q.filter(Distribusi.status == DistribusiStatus.DISTRIBUTED).count()
    rejected    = q.filter(Distribusi.status == DistribusiStatus.REJECTED).count()
    total_nominal = (
        db.query(func.coalesce(func.sum(Distribusi.nominal), 0))
        .filter(
            Distribusi.petugas_id == current_user.id,
            Distribusi.tanggal_distribusi >= cutoff,
        )
        .scalar() or 0
    )

    # 7 distribusi terakhir
    recent = (
        db.query(Distribusi)
        .filter(Distribusi.petugas_id == current_user.id)
        .order_by(Distribusi.tanggal_distribusi.desc())
        .limit(7)
        .all()
    )

    return {
        "periode_hari": hari,
        "sejak": cutoff.strftime("%Y-%m-%d"),
        "total_distribusi": total,
        "distributed": distributed,
        "rejected": rejected,
        "total_nominal": float(total_nominal),
        "riwayat_terakhir": [
            {
                "no_seri": d.no_seri,
                "penerima_id": d.penerima_id,
                "jenis_bantuan": d.jenis_bantuan,
                "nominal": d.nominal,
                "status": d.status.value,
                "tanggal": d.tanggal_distribusi.strftime("%Y-%m-%d %H:%M"),
            }
            for d in recent
        ],
    }
