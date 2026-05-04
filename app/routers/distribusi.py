"""Distribusi endpoints.

Izin:
  Buat / scan QR : punya task permission 'distribusi' (Administrator, Admin, atau Petugas-distribusi)
  Lihat & export : semua authenticated
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session, selectinload

from app.core.ws_manager import broadcast_sync
from app.database import get_db
from app.dependencies import check_category_access, get_allowed_category_ids, get_current_user, require_distribusi
from app.models import Distribusi, DistribusiStatus, Penerima, PenerimaKategori, User
from app.models.penerima import PenerimaStatus
from app.schemas.distribusi import DistribusiCreate, DistribusiOut
from app.services.distribusi_service import create_distribusi
from app.services.export_service import export_distribusi_xlsx, export_filename

router = APIRouter(prefix="/distribusi", tags=["distribusi"])


def _penerima_kategori_ids(db: Session, penerima_id: int) -> List[int]:
    rows = db.query(PenerimaKategori.kategori_id).filter(PenerimaKategori.penerima_id == penerima_id).all()
    return [r.kategori_id for r in rows]


@router.post("", response_model=DistribusiOut, status_code=status.HTTP_201_CREATED)
def create(
    payload: DistribusiCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_distribusi),
):
    # Cek kategori access
    kat_ids = _penerima_kategori_ids(db, payload.penerima_id)
    if not check_category_access(user, kat_ids):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Tidak berwenang: penerima ini bukan dalam kategori yang ditugaskan kepada Anda",
        )
    try:
        dist, fraud = create_distribusi(
            db,
            penerima_id=payload.penerima_id,
            jenis_bantuan=payload.jenis_bantuan,
            nominal=payload.nominal,
            keterangan=payload.keterangan,
            petugas=user,
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))

    broadcast_sync("distribusi.created", {
        "no_seri": dist.no_seri,
        "penerima_id": dist.penerima_id,
        "status": dist.status.value,
        "fraud": bool(fraud),
    })
    return dist


@router.get("", response_model=List[DistribusiOut])
def list_distribusi(
    penerima_id: Optional[int] = None,
    status_filter: Optional[DistribusiStatus] = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    allowed_cat_ids = get_allowed_category_ids(current_user)
    q = db.query(Distribusi).order_by(Distribusi.tanggal_distribusi.desc())
    if penerima_id is not None:
        q = q.filter(Distribusi.penerima_id == penerima_id)
    if status_filter is not None:
        q = q.filter(Distribusi.status == status_filter)
    if allowed_cat_ids is not None:
        q = q.join(
            PenerimaKategori, PenerimaKategori.penerima_id == Distribusi.penerima_id
        ).filter(PenerimaKategori.kategori_id.in_(allowed_cat_ids)).distinct()
    return q.offset((page - 1) * size).limit(size).all()


@router.get("/export/xlsx")
def export_distribusi_excel(
    status_filter: Optional[DistribusiStatus] = Query(None, alias="status"),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Export distribusi ke Excel (semua authenticated)."""
    q = (
        db.query(Distribusi)
        .options(selectinload(Distribusi.penerima), selectinload(Distribusi.petugas))
        .order_by(Distribusi.tanggal_distribusi.desc())
    )
    if status_filter is not None:
        q = q.filter(Distribusi.status == status_filter)
    rows = q.all()
    blob = export_distribusi_xlsx(rows)
    fname = export_filename("distribusi")
    return Response(
        content=blob,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={fname}"},
    )


@router.post("/{penerima_id}/confirm", response_model=DistribusiOut)
def confirm_distribusi(
    penerima_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_distribusi),
):
    """Konfirmasi distribusi bantuan kepada penerima.

    Mengubah status penerima dari MENUNGGU_DISTRIBUSI → SUDAH_DISTRIBUSI.
    Tidak bisa diklik 2x (idempoten).
    """
    penerima = db.query(Penerima).filter(Penerima.id == penerima_id).first()
    if not penerima:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Penerima tidak ditemukan")

    # Cek kategori access
    kat_ids = _penerima_kategori_ids(db, penerima_id)
    if not check_category_access(user, kat_ids):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Tidak berwenang: penerima ini bukan dalam kategori yang ditugaskan kepada Anda",
        )

    # Penerima Bulanan hanya bisa dikonfirmasi via menu Distribusi Bulanan
    from app.models import Kategori as _Kat
    kat_bulanan = db.query(_Kat).filter(_Kat.nama == "Penerima Bulanan").first()
    if kat_bulanan:
        is_bulanan = db.query(PenerimaKategori).filter(
            PenerimaKategori.penerima_id == penerima_id,
            PenerimaKategori.kategori_id == kat_bulanan.id,
        ).first()
        if is_bulanan:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Penerima Bulanan hanya bisa dikonfirmasi melalui menu Distribusi Bulanan",
            )

    if penerima.status_bantuan == PenerimaStatus.SUDAH_DISTRIBUSI:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Distribusi sudah pernah dilakukan untuk penerima ini",
        )

    try:
        dist, _ = create_distribusi(
            db,
            penerima_id=penerima_id,
            jenis_bantuan="Bantuan Sosial BANI INSAN PEDULI",
            nominal=0,
            keterangan=None,
            petugas=user,
            skip_double_check=True,
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))

    penerima.status_bantuan = PenerimaStatus.SUDAH_DISTRIBUSI
    db.commit()
    db.refresh(dist)

    broadcast_sync("distribusi.confirmed", {
        "penerima_id": penerima_id,
        "no_seri": dist.no_seri,
        "petugas": user.full_name,
    })
    return dist


@router.get("/{dist_id}", response_model=DistribusiOut)
def get_distribusi(
    dist_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    d = db.query(Distribusi).filter(Distribusi.id == dist_id).first()
    if not d:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Distribusi tidak ditemukan")
    return d
