"""Penerima endpoints — CRUD, import, export.

Setiap create/update otomatis:
  1. Hitung priority_score & priority_level (AI scoring)
  2. Jalankan fraud detection (RapidFuzz + NIK check)
  3. Persist FraudLog kalau ada match suspicious
  4. Broadcast WebSocket event

Izin per role:
  Lihat/list   : semua authenticated
  Buat/edit    : ADMIN, PETUGAS, PETUGAS_ENTRI
  Import Excel : ADMIN, PETUGAS, PETUGAS_ENTRI
  Export Excel : ADMIN, PETUGAS, PETUGAS_ENTRI, PETUGAS_DISTRIBUSI, SUPERVISOR
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.ws_manager import broadcast_sync
from app.database import get_db
from app.dependencies import check_category_access, get_allowed_category_ids, get_current_user, require_entri, require_export
from app.models import Distribusi, Kategori, Penerima, PenerimaKategori, User
from app.models.penerima import PriorityLevel, PenerimaStatus
from app.schemas.penerima import (
    PenerimaCreate,
    PenerimaListResponse,
    PenerimaOut,
    PenerimaUpdate,
)
from app.services.export_service import export_filename, export_penerima_xlsx, get_penerima_import_template
from datetime import datetime
from sqlalchemy import func
from app.services.fraud_service import apply_fraud_findings, detect_fraud
from app.services.import_service import import_penerima_xlsx
from app.services.priority_service import update_priority
from app.services.distribusi_bulanan_service import (
    NAMA_KATEGORI_BULANAN,
    generate_untuk_penerima,
)

router = APIRouter(prefix="/penerima", tags=["penerima"])


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_kategori(db: Session, kategori_ids: List[int]) -> List[Kategori]:
    if not kategori_ids:
        return []
    rows = (
        db.query(Kategori)
        .filter(Kategori.id.in_(kategori_ids), Kategori.is_active.is_(True))
        .all()
    )
    found = {k.id for k in rows}
    missing = set(kategori_ids) - found
    if missing:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Kategori tidak ditemukan: {sorted(missing)}",
        )
    return rows


def _set_kategori(db: Session, penerima: Penerima, kategori_objs: List[Kategori]) -> None:
    db.query(PenerimaKategori).filter(
        PenerimaKategori.penerima_id == penerima.id
    ).delete(synchronize_session=False)
    db.flush()
    for k in kategori_objs:
        db.add(PenerimaKategori(penerima_id=penerima.id, kategori_id=k.id))
    db.flush()


def _attach_kategori_for_response(p: Penerima) -> dict:
    data = PenerimaOut.model_validate(p).model_dump()
    data["kategori"] = [
        {
            "id": k.id,
            "nama": k.nama,
            "deskripsi": k.deskripsi,
            "weight": k.weight,
            "is_default": k.is_default,
            "is_active": k.is_active,
            "created_at": k.created_at,
        }
        for k in p.kategori_list
    ]
    return data


# ── Endpoint: import & template (harus sebelum /{id}) ────────────────────────

@router.get("/import/template")
def download_import_template(_: User = Depends(require_export)):
    """Unduh template Excel untuk import data penerima."""
    blob = get_penerima_import_template()
    return Response(
        content=blob,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=template_import_penerima.xlsx"},
    )


@router.post("/import/xlsx", status_code=status.HTTP_200_OK)
def import_penerima_from_excel(
    file: UploadFile = File(..., description="File Excel (.xlsx) sesuai template"),
    db: Session = Depends(get_db),
    _: User = Depends(require_entri),
):
    """Import data penerima massal dari file Excel.

    - Kolom: NIK | Nama Lengkap | Tempat Lahir | Tanggal Lahir | Jenis Kelamin |
             Alamat | No Telp | Penghasilan | Jumlah Tanggungan | Status Rumah | Nama Kategori
    - Baris 1 = header, baris 2 = petunjuk, baris 3+ = data.
    - NIK duplikat dilewati.
    - Fraud detection + priority scoring otomatis.
    - Unduh template: GET /penerima/import/template
    """
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "File harus berformat .xlsx")

    content = file.file.read()
    if len(content) > 10 * 1024 * 1024:  # 10 MB
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ukuran file maksimal 10 MB")

    result = import_penerima_xlsx(db, content)

    return {
        "total_rows": result.total_rows,
        "imported": result.imported,
        "skipped_duplicate": result.skipped_duplicate,
        "failed": result.failed,
        "errors": [
            {"row": e.row, "nik": e.nik, "message": e.message}
            for e in result.errors
        ],
    }


@router.get("/export/xlsx")
def export_penerima_excel(
    kategori_id: Optional[int] = None,
    priority: Optional[PriorityLevel] = None,
    fraud_only: bool = False,
    db: Session = Depends(get_db),
    _: User = Depends(require_export),
):
    """Export data penerima ke Excel."""
    query = db.query(Penerima).options(
        selectinload(Penerima.kategori_assoc).selectinload(PenerimaKategori.kategori)
    )
    if kategori_id is not None:
        query = query.join(PenerimaKategori).filter(PenerimaKategori.kategori_id == kategori_id)
    if priority is not None:
        query = query.filter(Penerima.priority_level == priority)
    if fraud_only:
        query = query.filter(Penerima.fraud_flag.is_(True))

    rows = query.order_by(Penerima.priority_score.desc()).all()
    blob = export_penerima_xlsx(rows)
    fname = export_filename("penerima")
    return Response(
        content=blob,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={fname}"},
    )


# ── Endpoint: CRUD ────────────────────────────────────────────────────────────

@router.get("", response_model=PenerimaListResponse)
def list_penerima(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    q: Optional[str] = Query(None, description="Cari nama / NIK / alamat"),
    kategori_id: Optional[int] = Query(None),
    exclude_kategori_id: Optional[int] = Query(None, description="Kecualikan penerima yang ada di kategori ini"),
    priority: Optional[PriorityLevel] = Query(None),
    status_bantuan: Optional[PenerimaStatus] = Query(None),
    bulan: Optional[int] = Query(None, ge=1, le=12, description="Filter bulan pendaftaran (1–12)"),
    tahun: Optional[int] = Query(None, description="Filter tahun pendaftaran, misal 2025"),
    fraud_only: bool = Query(False),
    sort_by: str = Query("created_at", pattern="^(priority_score|created_at|nama)$"),
    sort_dir: str = Query("desc", pattern="^(asc|desc)$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from sqlalchemy import select as sa_select
    from app.dependencies import _implied_kategori_ids

    allowed_cat_ids = get_allowed_category_ids(current_user)
    # Petugas yang dibatasi kategori tetap berhak ke kategori yang diturunkan
    # dari izin (mis. pendataan_bulanan → Penerima Bulanan).
    if allowed_cat_ids is not None:
        allowed_cat_ids = list(set(allowed_cat_ids) | set(_implied_kategori_ids(current_user, db)))

    query = db.query(Penerima).options(
        selectinload(Penerima.kategori_assoc).selectinload(PenerimaKategori.kategori)
    ).filter(Penerima.is_active.is_(True))

    # Pakai subquery untuk semua filter berbasis kategori — hindari duplicate JOIN.
    if allowed_cat_ids is not None:
        subq_allowed = sa_select(PenerimaKategori.penerima_id).where(
            PenerimaKategori.kategori_id.in_(allowed_cat_ids)
        ).scalar_subquery()
        query = query.filter(Penerima.id.in_(subq_allowed))
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                Penerima.nama.ilike(like),
                Penerima.nik.ilike(like),
                Penerima.alamat.ilike(like),
                Penerima.kode_seri.ilike(like),
            )
        )
    if kategori_id is not None:
        subq_kat = sa_select(PenerimaKategori.penerima_id).where(
            PenerimaKategori.kategori_id == kategori_id
        ).scalar_subquery()
        query = query.filter(Penerima.id.in_(subq_kat))
    if exclude_kategori_id is not None:
        subq_excl = sa_select(PenerimaKategori.penerima_id).where(
            PenerimaKategori.kategori_id == exclude_kategori_id
        ).scalar_subquery()
        query = query.filter(~Penerima.id.in_(subq_excl))
    if priority is not None:
        query = query.filter(Penerima.priority_level == priority)
    if status_bantuan is not None:
        query = query.filter(Penerima.status_bantuan == status_bantuan)
    if bulan is not None:
        from sqlalchemy import extract
        query = query.filter(extract('month', Penerima.created_at) == bulan)
    if tahun is not None:
        from sqlalchemy import extract
        query = query.filter(extract('year', Penerima.created_at) == tahun)
    if fraud_only:
        query = query.filter(Penerima.fraud_flag.is_(True))

    sort_col = {
        "priority_score": Penerima.priority_score,
        "created_at": Penerima.created_at,
        "nama": Penerima.nama,
    }[sort_by]
    query = query.order_by(sort_col.desc() if sort_dir == "desc" else sort_col.asc())

    total = query.count()
    rows = query.offset((page - 1) * size).limit(size).all()
    return {"total": total, "page": page, "size": size, "items": [_attach_kategori_for_response(p) for p in rows]}


@router.get("/{penerima_id}", response_model=PenerimaOut)
def get_penerima(
    penerima_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    p = (
        db.query(Penerima)
        .options(selectinload(Penerima.kategori_assoc).selectinload(PenerimaKategori.kategori))
        .filter(Penerima.id == penerima_id)
        .first()
    )
    if not p:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Penerima tidak ditemukan")
    return _attach_kategori_for_response(p)


@router.get("/{penerima_id}/detail-lengkap")
def get_penerima_detail_lengkap(
    penerima_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Detail lengkap penerima + 10 riwayat distribusi terakhir.
    Dipakai untuk modal detail saat klik kode seri."""
    p = (
        db.query(Penerima)
        .options(selectinload(Penerima.kategori_assoc).selectinload(PenerimaKategori.kategori))
        .filter(Penerima.id == penerima_id)
        .first()
    )
    if not p:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Penerima tidak ditemukan")

    riwayat = (
        db.query(Distribusi)
        .filter(Distribusi.penerima_id == penerima_id)
        .order_by(Distribusi.tanggal_distribusi.desc())
        .limit(10)
        .all()
    )

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
        "riwayat_distribusi": [
            {
                "no_seri":      d.no_seri or "-",
                "jenis_bantuan": d.jenis_bantuan or "-",
                "nominal":      d.nominal or 0,
                "status":       d.status.value,
                "tanggal":      d.tanggal_distribusi.strftime("%Y-%m-%d %H:%M"),
            }
            for d in riwayat
        ],
    }


_KODE_SERI_PREFIX = {
    "Penerima Bulanan": "PB",
    "Fakir Miskin": "FM",
    "Anak Yatim Piatu": "AYP",
    "Disabilitas": "DIS",
}


def _maybe_generate_bulanan(db: Session, penerima_id: int, kategori_objs) -> None:
    """Auto-generate 12 bulan distribusi jika penerima masuk kategori Bulanan."""
    if any(k.nama == NAMA_KATEGORI_BULANAN for k in kategori_objs):
        tahun = datetime.utcnow().year
        generate_untuk_penerima(db, penerima_id, tahun)


def _generate_kode_seri(db: Session, kategori_objs) -> str:
    if kategori_objs:
        primary = max(kategori_objs, key=lambda k: k.weight)
        prefix = _KODE_SERI_PREFIX.get(primary.nama, "UMM")
    else:
        prefix = "UMM"
    ym = datetime.utcnow().strftime("%Y%m")
    like_pat = f"{prefix}-{ym}-%"
    count = db.query(func.count(Penerima.id)).filter(Penerima.kode_seri.like(like_pat)).scalar() or 0
    return f"{prefix}-{ym}-{count + 1:05d}"


@router.post("", response_model=PenerimaOut, status_code=status.HTTP_201_CREATED)
def create_penerima(
    payload: PenerimaCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_entri),
):
    kategori_objs = _load_kategori(db, payload.kategori_ids)
    # Petugas dengan batasan kategori hanya boleh entri penerima dalam kategorinya
    # (kategori juga bisa diturunkan dari izin: pendataan_bulanan → Penerima Bulanan, dst.)
    if payload.kategori_ids and not check_category_access(current_user, payload.kategori_ids, db):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Tidak berwenang: setidaknya satu kategori yang dipilih di luar wewenang Anda",
        )
    data = payload.model_dump(exclude={"kategori_ids"})
    p = Penerima(
        **data,
        status_bantuan=PenerimaStatus.MENUNGGU_DISTRIBUSI,
        created_by_id=current_user.id,
    )
    db.add(p)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "NIK sudah terdaftar")
    _set_kategori(db, p, kategori_objs)
    db.flush()
    p.kode_seri = _generate_kode_seri(db, kategori_objs)
    db.flush()
    update_priority(p, db)
    findings = detect_fraud(db, p)
    apply_fraud_findings(db, p, findings)
    _maybe_generate_bulanan(db, p.id, kategori_objs)
    db.commit()
    db.refresh(p)
    broadcast_sync("penerima.created", {
        "id": p.id, "nik": p.nik, "nama": p.nama,
        "kode_seri": p.kode_seri, "status_bantuan": p.status_bantuan.value,
        "priority_level": p.priority_level.value, "fraud_flag": p.fraud_flag,
    })
    return _attach_kategori_for_response(p)


@router.put("/{penerima_id}", response_model=PenerimaOut)
def update_penerima(
    penerima_id: int,
    payload: PenerimaUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_entri),
):
    p = db.query(Penerima).filter(Penerima.id == penerima_id).first()
    if not p:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Penerima tidak ditemukan")
    data = payload.model_dump(exclude_unset=True)
    kategori_ids = data.pop("kategori_ids", None)
    for field, value in data.items():
        setattr(p, field, value)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "NIK sudah digunakan oleh penerima lain")
    new_kategori_objs = None
    if kategori_ids is not None:
        new_kategori_objs = _load_kategori(db, kategori_ids)
        _set_kategori(db, p, new_kategori_objs)
    db.refresh(p)
    update_priority(p, db)
    findings = detect_fraud(db, p)
    apply_fraud_findings(db, p, findings)
    if new_kategori_objs is not None:
        _maybe_generate_bulanan(db, p.id, new_kategori_objs)
    db.commit()
    db.refresh(p)
    broadcast_sync("penerima.updated", {
        "id": p.id, "nik": p.nik, "nama": p.nama,
        "priority_level": p.priority_level.value, "fraud_flag": p.fraud_flag,
    })
    return _attach_kategori_for_response(p)


@router.delete("/{penerima_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_penerima(
    penerima_id: int,
    hard: bool = Query(False, description="True = hapus permanen, False = soft delete"),
    db: Session = Depends(get_db),
    _: User = Depends(require_entri),
):
    p = db.query(Penerima).filter(Penerima.id == penerima_id).first()
    if not p:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Penerima tidak ditemukan")
    if hard:
        db.delete(p)
    else:
        p.is_active = False
    db.commit()
    return None
