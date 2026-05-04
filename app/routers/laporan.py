"""Laporan endpoints: harian dan bulanan.

Covers all distribution sources:
  - Distribusi reguler  (tanggal_distribusi, nominal, petugas)
  - Distribusi bulanan  (per penerima bulanan, tracked by confirmed_at)
  - Distribusi sosial   (Fakir Miskin / Disabilitas / Anak Yatim Piatu, confirmed_at)

GET /laporan/harian?tanggal=YYYY-MM-DD
GET /laporan/bulanan?year=YYYY&month=MM
"""
from calendar import monthrange
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, case
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_allowed_category_ids, require_perm
from app.models import Distribusi, DistribusiStatus, Kategori, Penerima, PenerimaKategori, User
from app.models.distribusi_bulanan import DistribusiBulanan, StatusBulanan
from app.models.distribusi_sosial import DistribusiSosial, StatusSosial
from app.models.penerima import PenerimaStatus

router = APIRouter(prefix="/laporan", tags=["laporan"])

require_laporan = require_perm("laporan_distribusi")

NAMA_BULANAN = "Penerima Bulanan"
NAMA_SOSIAL  = ["Fakir Miskin", "Disabilitas", "Anak Yatim Piatu"]


def _kat_bulanan_id(db: Session) -> int | None:
    row = db.query(Kategori.id).filter(Kategori.nama == NAMA_BULANAN).first()
    return row.id if row else None


def _kat_sosial_map(db: Session) -> dict[str, int]:
    rows = db.query(Kategori.nama, Kategori.id).filter(Kategori.nama.in_(NAMA_SOSIAL)).all()
    return {r.nama: r.id for r in rows}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fetch_by_ids(db: Session, model, ids: set):
    if not ids:
        return {}
    rows = db.query(model).filter(model.id.in_(ids)).all()
    return {r.id: r for r in rows}


def _reg_kat_map(db: Session, pids: set[int]) -> dict[int, str]:
    """penerima_id → first matching category name (for reguler distribusi)."""
    if not pids:
        return {}
    rows = (
        db.query(PenerimaKategori.penerima_id, Kategori.nama)
        .join(Kategori, Kategori.id == PenerimaKategori.kategori_id)
        .filter(PenerimaKategori.penerima_id.in_(pids))
        .all()
    )
    result: dict[int, str] = {}
    for pid, kname in rows:
        if pid not in result:
            result[pid] = kname
    return result


# ── Laporan Harian ────────────────────────────────────────────────────────────

@router.get("/harian")
def laporan_harian(
    tanggal: Optional[date] = Query(None, description="Format YYYY-MM-DD, default hari ini"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_laporan),
) -> Dict[str, Any]:
    if tanggal is None:
        tanggal = date.today()

    allowed     = get_allowed_category_ids(current_user)
    start       = datetime.combine(tanggal, datetime.min.time())
    end         = datetime.combine(tanggal, datetime.max.time())
    bulanan_id  = _kat_bulanan_id(db)
    sosial_map  = _kat_sosial_map(db)
    sosial_ids  = list(sosial_map.values())

    can_bulanan    = allowed is None or (bulanan_id is not None and bulanan_id in allowed)
    visible_sosial = sosial_ids if allowed is None else [i for i in sosial_ids if i in allowed]

    # ── Reguler ──────────────────────────────────────────────────
    reg_q = db.query(Distribusi).filter(
        Distribusi.tanggal_distribusi >= start,
        Distribusi.tanggal_distribusi <= end,
        Distribusi.status == DistribusiStatus.DISTRIBUTED,
    )
    if allowed is not None:
        reg_q = reg_q.join(
            PenerimaKategori, PenerimaKategori.penerima_id == Distribusi.penerima_id
        ).filter(PenerimaKategori.kategori_id.in_(allowed))
    reg_rows = reg_q.order_by(Distribusi.tanggal_distribusi.desc()).all()

    # ── Bulanan (confirmed today) ────────────────────────────────
    bul_rows: list = []
    if can_bulanan and bulanan_id is not None:
        bul_rows = (
            db.query(DistribusiBulanan)
            .filter(
                DistribusiBulanan.confirmed_at >= start,
                DistribusiBulanan.confirmed_at <= end,
                DistribusiBulanan.status == StatusBulanan.SUDAH_DITERIMA,
            )
            .order_by(DistribusiBulanan.confirmed_at.desc())
            .all()
        )

    # ── Sosial (confirmed today, with kategori name) ─────────────
    sos_tuples: list = []
    if visible_sosial:
        sos_tuples = (
            db.query(DistribusiSosial, Kategori.nama.label("kat_nama"))
            .join(PenerimaKategori, PenerimaKategori.penerima_id == DistribusiSosial.penerima_id)
            .join(Kategori, Kategori.id == PenerimaKategori.kategori_id)
            .filter(
                DistribusiSosial.confirmed_at >= start,
                DistribusiSosial.confirmed_at <= end,
                DistribusiSosial.status == StatusSosial.SUDAH_DITERIMA,
                PenerimaKategori.kategori_id.in_(visible_sosial),
            )
            .order_by(DistribusiSosial.confirmed_at.desc())
            .all()
        )

    # ── Caches ───────────────────────────────────────────────────
    sos_objs  = [t[0] for t in sos_tuples]
    all_pids  = {r.penerima_id for r in (reg_rows + bul_rows + sos_objs)}
    all_uids  = (
        {r.petugas_id for r in reg_rows if r.petugas_id}
        | {r.confirmed_by_id for r in bul_rows if r.confirmed_by_id}
        | {r.confirmed_by_id for r in sos_objs if r.confirmed_by_id}
    )
    penerima_map = _fetch_by_ids(db, Penerima, all_pids)
    user_map     = _fetch_by_ids(db, User, all_uids)
    kat_map_reg  = _reg_kat_map(db, {r.penerima_id for r in reg_rows})

    # ── Build detail ─────────────────────────────────────────────
    detail: list  = []
    petugas_count: dict[str, int] = {}
    kat_count:     dict[str, int] = {}

    def _row(sumber, p, ptgs, kategori, jenis, nominal, status_label, tgl_jam):
        pn = ptgs.full_name if ptgs else "-"
        petugas_count[pn] = petugas_count.get(pn, 0) + 1
        kat_count[kategori] = kat_count.get(kategori, 0) + 1
        return {
            "sumber":        sumber,
            "penerima_id":   p.id if p else None,
            "kode_seri":     p.kode_seri if p else "-",
            "penerima_nama": p.nama if p else "-",
            "penerima_nik":  p.nik  if p else "-",
            "kategori":      kategori,
            "jenis_bantuan": jenis,
            "nominal":       nominal,
            "status_label":  status_label,
            "petugas_nama":  pn,
            "tanggal_jam":   tgl_jam,
        }

    for d in reg_rows[:400]:
        detail.append(_row(
            "Reguler",
            penerima_map.get(d.penerima_id),
            user_map.get(d.petugas_id) if d.petugas_id else None,
            kat_map_reg.get(d.penerima_id, "-"),
            d.jenis_bantuan or "-",
            d.nominal or 0,
            "Terdistribusi",
            d.tanggal_distribusi.strftime("%Y-%m-%d %H:%M"),
        ))

    for d in bul_rows[:200]:
        detail.append(_row(
            "Bulanan",
            penerima_map.get(d.penerima_id),
            user_map.get(d.confirmed_by_id) if d.confirmed_by_id else None,
            NAMA_BULANAN, "-", 0,
            "Sudah Diterima",
            d.confirmed_at.strftime("%Y-%m-%d %H:%M") if d.confirmed_at else "-",
        ))

    for d, kat_nama in sos_tuples[:200]:
        detail.append(_row(
            "Sosial",
            penerima_map.get(d.penerima_id),
            user_map.get(d.confirmed_by_id) if d.confirmed_by_id else None,
            kat_nama, "-", 0,
            "Sudah Diterima",
            d.confirmed_at.strftime("%Y-%m-%d %H:%M") if d.confirmed_at else "-",
        ))

    per_kategori = [{"kategori": k, "jumlah": v} for k, v in sorted(kat_count.items())]
    per_petugas  = [
        {"nama": n, "jumlah": j}
        for n, j in sorted(petugas_count.items(), key=lambda x: -x[1])
    ]

    return {
        "tanggal":          tanggal.isoformat(),
        "reguler_total":    len(reg_rows),
        "bulanan_total":    len(bul_rows),
        "sosial_total":     len(sos_tuples),
        "total_distribusi": len(reg_rows) + len(bul_rows) + len(sos_tuples),
        "total_nominal":    sum(d.nominal or 0 for d in reg_rows),
        "per_kategori":     per_kategori,
        "per_petugas":      per_petugas,
        "detail":           detail,
    }


# ── Laporan Bulanan ───────────────────────────────────────────────────────────

@router.get("/bulanan")
def laporan_bulanan(
    year:  Optional[int] = Query(None, ge=2020, le=2100),
    month: Optional[int] = Query(None, ge=1, le=12),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_laporan),
) -> Dict[str, Any]:
    now = datetime.utcnow()
    if year  is None: year  = now.year
    if month is None: month = now.month

    allowed        = get_allowed_category_ids(current_user)
    _, days        = monthrange(year, month)
    start          = datetime(year, month, 1)
    end            = datetime(year, month, days, 23, 59, 59)
    bulanan_id     = _kat_bulanan_id(db)
    sosial_map     = _kat_sosial_map(db)
    sosial_ids     = list(sosial_map.values())

    can_bulanan    = allowed is None or (bulanan_id is not None and bulanan_id in allowed)
    visible_sosial = sosial_ids if allowed is None else [i for i in sosial_ids if i in allowed]

    base_filter = [
        Distribusi.tanggal_distribusi >= start,
        Distribusi.tanggal_distribusi <= end,
        Distribusi.status == DistribusiStatus.DISTRIBUTED,
    ]

    def _reg_join(q):
        if allowed is not None:
            return q.join(
                PenerimaKategori, PenerimaKategori.penerima_id == Distribusi.penerima_id
            ).filter(PenerimaKategori.kategori_id.in_(allowed))
        return q

    # ── Reguler totals ────────────────────────────────────────────
    reg_total   = _reg_join(db.query(func.count(Distribusi.id)).filter(*base_filter)).scalar() or 0
    reg_nominal = float(_reg_join(db.query(func.sum(Distribusi.nominal)).filter(*base_filter)).scalar() or 0)

    # Penerima status (global, for reguler category)
    def _count_status(status_val):
        q = db.query(func.count(Penerima.id)).filter(
            Penerima.status_bantuan == status_val,
            Penerima.is_active.is_(True),
        )
        if allowed is not None:
            q = q.join(PenerimaKategori, PenerimaKategori.penerima_id == Penerima.id
                       ).filter(PenerimaKategori.kategori_id.in_(allowed))
        return q.scalar() or 0

    total_menunggu = _count_status(PenerimaStatus.MENUNGGU_DISTRIBUSI)
    total_sudah    = _count_status(PenerimaStatus.SUDAH_DISTRIBUSI)

    # ── Reguler per kategori ──────────────────────────────────────
    kat_q = (
        db.query(Kategori.nama, func.count(Distribusi.id).label("jumlah"))
        .join(PenerimaKategori, PenerimaKategori.penerima_id == Distribusi.penerima_id)
        .join(Kategori, Kategori.id == PenerimaKategori.kategori_id)
        .filter(*base_filter)
    )
    if allowed is not None:
        kat_q = kat_q.filter(Kategori.id.in_(allowed))
    per_kategori: list = [
        {"kategori": r.nama, "jumlah": int(r.jumlah)}
        for r in kat_q.group_by(Kategori.id, Kategori.nama).all()
    ]

    # ── Bulanan stats (sudah/belum this month) ────────────────────
    bul_data: dict | None = None
    if can_bulanan and bulanan_id is not None:
        row = (
            db.query(
                func.count(DistribusiBulanan.id).label("total"),
                func.sum(case((DistribusiBulanan.status == StatusBulanan.SUDAH_DITERIMA, 1), else_=0)).label("sudah"),
            )
            .join(Penerima, Penerima.id == DistribusiBulanan.penerima_id)
            .join(PenerimaKategori, PenerimaKategori.penerima_id == DistribusiBulanan.penerima_id)
            .filter(
                DistribusiBulanan.bulan == month,
                DistribusiBulanan.tahun == year,
                Penerima.is_active.is_(True),
                PenerimaKategori.kategori_id == bulanan_id,
            )
            .first()
        )
        bul_total = int(row.total or 0) if row else 0
        bul_sudah = int(row.sudah or 0) if row else 0
        bul_data = {
            "total":     bul_total,
            "sudah":     bul_sudah,
            "belum":     bul_total - bul_sudah,
            "pct_sudah": round(bul_sudah / bul_total * 100, 1) if bul_total else 0.0,
        }
        if bul_sudah > 0:
            per_kategori.append({"kategori": NAMA_BULANAN, "jumlah": bul_sudah})

    # ── Sosial stats per kategori ─────────────────────────────────
    sosial_per_kat: list = []
    if visible_sosial:
        for kat_nama, kat_id in sosial_map.items():
            if kat_id not in visible_sosial:
                continue
            row = (
                db.query(
                    func.count(DistribusiSosial.id).label("total"),
                    func.sum(case((DistribusiSosial.status == StatusSosial.SUDAH_DITERIMA, 1), else_=0)).label("sudah"),
                )
                .join(Penerima, Penerima.id == DistribusiSosial.penerima_id)
                .join(PenerimaKategori, PenerimaKategori.penerima_id == DistribusiSosial.penerima_id)
                .filter(
                    DistribusiSosial.bulan == month,
                    DistribusiSosial.tahun == year,
                    Penerima.is_active.is_(True),
                    PenerimaKategori.kategori_id == kat_id,
                )
                .first()
            )
            sos_total = int(row.total or 0) if row else 0
            sos_sudah = int(row.sudah or 0) if row else 0
            sosial_per_kat.append({
                "nama":      kat_nama,
                "total":     sos_total,
                "sudah":     sos_sudah,
                "belum":     sos_total - sos_sudah,
                "pct_sudah": round(sos_sudah / sos_total * 100, 1) if sos_total else 0.0,
            })
            if sos_sudah > 0:
                per_kategori.append({"kategori": kat_nama, "jumlah": sos_sudah})

    # ── Per petugas (combined) ─────────────────────────────────────
    ptgs_count: dict[str, int] = {}

    for r in (
        _reg_join(
            db.query(User.full_name, func.count(Distribusi.id).label("jumlah"))
            .join(User, User.id == Distribusi.petugas_id)
            .filter(*base_filter)
        )
        .group_by(User.id, User.full_name)
        .all()
    ):
        ptgs_count[r.full_name] = ptgs_count.get(r.full_name, 0) + int(r.jumlah)

    if can_bulanan and bulanan_id is not None:
        for r in (
            db.query(User.full_name, func.count(DistribusiBulanan.id).label("jumlah"))
            .join(User, User.id == DistribusiBulanan.confirmed_by_id)
            .join(PenerimaKategori, PenerimaKategori.penerima_id == DistribusiBulanan.penerima_id)
            .filter(
                DistribusiBulanan.bulan == month,
                DistribusiBulanan.tahun == year,
                DistribusiBulanan.status == StatusBulanan.SUDAH_DITERIMA,
                PenerimaKategori.kategori_id == bulanan_id,
            )
            .group_by(User.id, User.full_name)
            .all()
        ):
            ptgs_count[r.full_name] = ptgs_count.get(r.full_name, 0) + int(r.jumlah)

    if visible_sosial:
        for r in (
            db.query(User.full_name, func.count(DistribusiSosial.id).label("jumlah"))
            .join(User, User.id == DistribusiSosial.confirmed_by_id)
            .join(PenerimaKategori, PenerimaKategori.penerima_id == DistribusiSosial.penerima_id)
            .filter(
                DistribusiSosial.bulan == month,
                DistribusiSosial.tahun == year,
                DistribusiSosial.status == StatusSosial.SUDAH_DITERIMA,
                PenerimaKategori.kategori_id.in_(visible_sosial),
            )
            .group_by(User.id, User.full_name)
            .all()
        ):
            ptgs_count[r.full_name] = ptgs_count.get(r.full_name, 0) + int(r.jumlah)

    per_petugas = [
        {"nama": n, "jumlah": j}
        for n, j in sorted(ptgs_count.items(), key=lambda x: -x[1])
    ]

    # ── Trend harian (combined confirmations per day) ─────────────
    trend_map: dict[str, int] = {}

    for r in (
        _reg_join(
            db.query(
                func.date(Distribusi.tanggal_distribusi).label("tgl"),
                func.count(Distribusi.id).label("jumlah"),
            ).filter(*base_filter)
        )
        .group_by(func.date(Distribusi.tanggal_distribusi))
        .all()
    ):
        k = str(r.tgl)
        trend_map[k] = trend_map.get(k, 0) + int(r.jumlah)

    if can_bulanan and bulanan_id is not None:
        for r in (
            db.query(
                func.date(DistribusiBulanan.confirmed_at).label("tgl"),
                func.count(DistribusiBulanan.id).label("jumlah"),
            )
            .join(PenerimaKategori, PenerimaKategori.penerima_id == DistribusiBulanan.penerima_id)
            .filter(
                DistribusiBulanan.bulan == month,
                DistribusiBulanan.tahun == year,
                DistribusiBulanan.status == StatusBulanan.SUDAH_DITERIMA,
                DistribusiBulanan.confirmed_at >= start,
                DistribusiBulanan.confirmed_at <= end,
                PenerimaKategori.kategori_id == bulanan_id,
            )
            .group_by(func.date(DistribusiBulanan.confirmed_at))
            .all()
        ):
            if r.tgl:
                k = str(r.tgl)
                trend_map[k] = trend_map.get(k, 0) + int(r.jumlah)

    if visible_sosial:
        for r in (
            db.query(
                func.date(DistribusiSosial.confirmed_at).label("tgl"),
                func.count(DistribusiSosial.id).label("jumlah"),
            )
            .join(PenerimaKategori, PenerimaKategori.penerima_id == DistribusiSosial.penerima_id)
            .filter(
                DistribusiSosial.bulan == month,
                DistribusiSosial.tahun == year,
                DistribusiSosial.status == StatusSosial.SUDAH_DITERIMA,
                DistribusiSosial.confirmed_at >= start,
                DistribusiSosial.confirmed_at <= end,
                PenerimaKategori.kategori_id.in_(visible_sosial),
            )
            .group_by(func.date(DistribusiSosial.confirmed_at))
            .all()
        ):
            if r.tgl:
                k = str(r.tgl)
                trend_map[k] = trend_map.get(k, 0) + int(r.jumlah)

    trend_harian = [
        {
            "tanggal": f"{year}-{month:02d}-{day:02d}",
            "jumlah":  trend_map.get(f"{year}-{month:02d}-{day:02d}", 0),
        }
        for day in range(1, days + 1)
    ]

    # ── Detail rows ───────────────────────────────────────────────
    reg_detail = (
        _reg_join(db.query(Distribusi).filter(*base_filter))
        .order_by(Distribusi.tanggal_distribusi.desc())
        .limit(250)
        .all()
    )

    bul_detail: list = []
    if can_bulanan and bulanan_id is not None:
        bul_detail = (
            db.query(DistribusiBulanan)
            .join(Penerima, Penerima.id == DistribusiBulanan.penerima_id)
            .join(PenerimaKategori, PenerimaKategori.penerima_id == DistribusiBulanan.penerima_id)
            .filter(
                DistribusiBulanan.bulan == month,
                DistribusiBulanan.tahun == year,
                Penerima.is_active.is_(True),
                PenerimaKategori.kategori_id == bulanan_id,
            )
            .order_by(DistribusiBulanan.status.asc(), Penerima.nama.asc())
            .limit(200)
            .all()
        )

    sos_detail_tuples: list = []
    if visible_sosial:
        sos_detail_tuples = (
            db.query(DistribusiSosial, Kategori.nama.label("kat_nama"))
            .join(PenerimaKategori, PenerimaKategori.penerima_id == DistribusiSosial.penerima_id)
            .join(Kategori, Kategori.id == PenerimaKategori.kategori_id)
            .join(Penerima, Penerima.id == DistribusiSosial.penerima_id)
            .filter(
                DistribusiSosial.bulan == month,
                DistribusiSosial.tahun == year,
                Penerima.is_active.is_(True),
                PenerimaKategori.kategori_id.in_(visible_sosial),
            )
            .order_by(DistribusiSosial.status.asc(), Penerima.nama.asc())
            .limit(200)
            .all()
        )

    all_d_pids = (
        {r.penerima_id for r in reg_detail}
        | {r.penerima_id for r in bul_detail}
        | {t[0].penerima_id for t in sos_detail_tuples}
    )
    all_d_uids = (
        {r.petugas_id for r in reg_detail if r.petugas_id}
        | {r.confirmed_by_id for r in bul_detail if r.confirmed_by_id}
        | {t[0].confirmed_by_id for t in sos_detail_tuples if t[0].confirmed_by_id}
    )
    p_map = _fetch_by_ids(db, Penerima, all_d_pids)
    u_map = _fetch_by_ids(db, User, all_d_uids)
    kat_reg = _reg_kat_map(db, {r.penerima_id for r in reg_detail})

    detail: list = []
    for d in reg_detail:
        p = p_map.get(d.penerima_id)
        ptgs = u_map.get(d.petugas_id) if d.petugas_id else None
        detail.append({
            "sumber":            "Reguler",
            "penerima_id":       p.id if p else None,
            "kode_seri":         p.kode_seri if p else "-",
            "penerima_nama":     p.nama if p else "-",
            "penerima_nik":      p.nik  if p else "-",
            "kategori":          kat_reg.get(d.penerima_id, "-"),
            "jenis_bantuan":     d.jenis_bantuan or "-",
            "nominal":           d.nominal or 0,
            "status_label":      "Terdistribusi",
            "petugas_nama":      ptgs.full_name if ptgs else "-",
            "tanggal_distribusi": d.tanggal_distribusi.strftime("%Y-%m-%d %H:%M"),
        })
    for d in bul_detail:
        p = p_map.get(d.penerima_id)
        ptgs = u_map.get(d.confirmed_by_id) if d.confirmed_by_id else None
        detail.append({
            "sumber":            "Bulanan",
            "penerima_id":       p.id if p else None,
            "kode_seri":         p.kode_seri if p else "-",
            "penerima_nama":     p.nama if p else "-",
            "penerima_nik":      p.nik  if p else "-",
            "kategori":          NAMA_BULANAN,
            "jenis_bantuan":     "-",
            "nominal":           0,
            "status_label":      "Sudah Diterima" if d.status == StatusBulanan.SUDAH_DITERIMA else "Belum Diterima",
            "petugas_nama":      ptgs.full_name if ptgs else "-",
            "tanggal_distribusi": d.confirmed_at.strftime("%Y-%m-%d %H:%M") if d.confirmed_at else "-",
        })
    for d, kat_nama in sos_detail_tuples:
        p = p_map.get(d.penerima_id)
        ptgs = u_map.get(d.confirmed_by_id) if d.confirmed_by_id else None
        detail.append({
            "sumber":            "Sosial",
            "penerima_id":       p.id if p else None,
            "kode_seri":         p.kode_seri if p else "-",
            "penerima_nama":     p.nama if p else "-",
            "penerima_nik":      p.nik  if p else "-",
            "kategori":          kat_nama,
            "jenis_bantuan":     "-",
            "nominal":           0,
            "status_label":      "Sudah Diterima" if d.status == StatusSosial.SUDAH_DITERIMA else "Belum Diterima",
            "petugas_nama":      ptgs.full_name if ptgs else "-",
            "tanggal_distribusi": d.confirmed_at.strftime("%Y-%m-%d %H:%M") if d.confirmed_at else "-",
        })

    BULAN = ["", "Januari", "Februari", "Maret", "April", "Mei", "Juni",
             "Juli", "Agustus", "September", "Oktober", "November", "Desember"]

    return {
        "year":                    year,
        "month":                   month,
        "bulan_nama":              BULAN[month],
        "reguler_total":           int(reg_total),
        "reguler_nominal":         reg_nominal,
        "total_distribusi":        int(reg_total),
        "total_nominal":           reg_nominal,
        "total_penerima_menunggu": total_menunggu,
        "total_penerima_sudah":    total_sudah,
        "bul_data":                bul_data,
        "sosial_per_kat":          sosial_per_kat,
        "per_kategori":            per_kategori,
        "per_petugas":             per_petugas,
        "trend_harian":            trend_harian,
        "detail":                  detail,
    }
