"""QR endpoints: generate QR + kartu penerima + scan (preview & confirm)."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session, selectinload

from app.core.ws_manager import broadcast_sync
from app.database import get_db
from app.dependencies import get_current_user, require_distribusi
from app.models import (
    DistribusiBulanan,
    Penerima,
    PenerimaKategori,
    StatusBulanan,
    User,
)

logger = logging.getLogger(__name__)
from app.schemas.distribusi import (
    DistribusiOut,
    ScanPreviewRequest,
    ScanPreviewResponse,
    ScanQRRequest,
)
from app.services.distribusi_bulanan_service import (
    NAMA_KATEGORI_BULANAN,
    konfirmasi as konfirmasi_bulanan,
)
from app.services.distribusi_service import create_distribusi
from app.services.qr_service import (
    build_payload,
    generate_qr_for_kode_seri,
    generate_qr_png,
    verify_payload,
)

router = APIRouter(tags=["qr"])


# ── QR PNG ──────────────────────────────────────────────────────────────────
@router.get("/qr/{penerima_id}")
def get_qr(
    penerima_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Return QR PNG untuk satu penerima. Payload QR = kode_seri."""
    p = db.query(Penerima).filter(Penerima.id == penerima_id).first()
    if not p:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Penerima tidak ditemukan")
    if not p.is_active:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Penerima non-aktif")
    if not p.kode_seri:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Penerima belum punya kode seri — tidak bisa generate QR",
        )
    try:
        payload, png = generate_qr_for_kode_seri(p.kode_seri)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    return Response(
        content=png,
        media_type="image/png",
        headers={"X-QR-Payload": payload},
    )


# ── Kartu Penerima (ID Card PNG) ────────────────────────────────────────────
@router.get("/qr/{penerima_id}/card")
def get_kartu_penerima(
    penerima_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Render kartu penerima PNG: identitas + QR. Cocok untuk dicetak."""
    p = (
        db.query(Penerima)
        .options(selectinload(Penerima.kategori_assoc).selectinload(PenerimaKategori.kategori))
        .filter(Penerima.id == penerima_id)
        .first()
    )
    if not p:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Penerima tidak ditemukan")
    if not p.kode_seri:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Penerima belum punya kode seri — tidak bisa cetak kartu",
        )

    from io import BytesIO
    from PIL import Image, ImageDraw, ImageFont

    # Generate QR (payload = kode_seri)
    try:
        payload = build_payload(p.kode_seri)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    qr_png = generate_qr_png(payload, box_size=8, border=2)
    qr_img = Image.open(BytesIO(qr_png))

    # Kanvas kartu (landscape, ~ID card ratio)
    W, H = 900, 540
    card = Image.new("RGB", (W, H), "white")
    draw = ImageDraw.Draw(card)

    # Header bar
    draw.rectangle([0, 0, W, 80], fill=(25, 91, 169))
    try:
        font_title = ImageFont.truetype("arialbd.ttf", 28)
        font_h = ImageFont.truetype("arialbd.ttf", 22)
        font_b = ImageFont.truetype("arial.ttf", 18)
        font_s = ImageFont.truetype("arial.ttf", 14)
    except Exception:
        font_title = ImageFont.load_default()
        font_h = ImageFont.load_default()
        font_b = ImageFont.load_default()
        font_s = ImageFont.load_default()

    draw.text((24, 24), "KARTU PENERIMA BANTUAN SOSIAL", fill="white", font=font_title)

    # QR di kanan
    qr_resized = qr_img.resize((260, 260))
    card.paste(qr_resized, (W - 290, 130))
    draw.text((W - 280, 400), "Pindai QR untuk verifikasi", fill="black", font=font_s)

    # Identitas di kiri
    x0, y0 = 30, 110
    line_h = 32
    kategori_names = ", ".join(k.nama for k in p.kategori_list) or "-"
    fields = [
        ("Nama", p.nama),
        ("NIK", p.nik),
        ("Kode Seri", p.kode_seri or "-"),
        ("Alamat", (p.alamat[:60] + "…") if len(p.alamat) > 60 else p.alamat),
        ("Kategori", kategori_names),
        ("No. Telp", p.no_telp or "-"),
    ]
    draw.text((x0, y0), "DATA PENERIMA", fill=(25, 91, 169), font=font_h)
    for i, (k, v) in enumerate(fields, start=1):
        y = y0 + 35 + i * line_h
        draw.text((x0, y), f"{k}", fill="gray", font=font_s)
        draw.text((x0 + 110, y - 3), f": {v}", fill="black", font=font_b)

    # Footer
    draw.line([(0, H - 40), (W, H - 40)], fill=(25, 91, 169), width=2)
    draw.text(
        (24, H - 30),
        f"Diterbitkan: {datetime.utcnow().strftime('%Y-%m-%d')}  •  Sistem Distribusi Bansos",
        fill="gray",
        font=font_s,
    )

    out = BytesIO()
    card.save(out, format="PNG")
    return Response(
        content=out.getvalue(),
        media_type="image/png",
        headers={
            "Content-Disposition": f'inline; filename="kartu-penerima-{p.id}.png"',
            "X-QR-Payload": payload,
        },
    )


# ── Helper: ambil status distribusi bulan ini ───────────────────────────────
def _build_preview(db: Session, p: Penerima) -> ScanPreviewResponse:
    now = datetime.utcnow()
    bulan, tahun = now.month, now.year

    # Cek apakah penerima ber-kategori bulanan
    kat_names = [k.nama for k in p.kategori_list]
    is_bulanan = NAMA_KATEGORI_BULANAN in kat_names

    sudah = False
    db_id = None
    if is_bulanan:
        row = (
            db.query(DistribusiBulanan)
            .filter(
                DistribusiBulanan.penerima_id == p.id,
                DistribusiBulanan.bulan == bulan,
                DistribusiBulanan.tahun == tahun,
            )
            .first()
        )
        if row:
            db_id = row.id
            sudah = row.status == StatusBulanan.SUDAH_DITERIMA

    warnings: List[str] = []
    if not p.is_active:
        warnings.append("Penerima non-aktif")
    if p.fraud_flag:
        warnings.append(f"Fraud flag: {p.fraud_reason or 'tanpa keterangan'}")
    if sudah:
        warnings.append("Penerima sudah menerima bantuan bulan ini")

    return ScanPreviewResponse(
        valid=True,
        penerima_id=p.id,
        nik=p.nik,
        nama=p.nama,
        alamat=p.alamat,
        no_telp=p.no_telp,
        kode_seri=p.kode_seri,
        is_active=p.is_active,
        kategori=kat_names,
        is_bulanan=is_bulanan,
        sudah_terima_bulan_ini=sudah,
        bulan_ini=bulan,
        tahun_ini=tahun,
        distribusi_bulanan_id=db_id,
        status_bantuan=p.status_bantuan.value if p.status_bantuan else None,
        fraud_flag=p.fraud_flag,
        fraud_reason=p.fraud_reason,
        warnings=warnings,
    )


# ── Scan: PREVIEW (tidak create distribusi) ────────────────────────────────
@router.post("/scan/preview", response_model=ScanPreviewResponse)
def scan_preview(
    payload: ScanPreviewRequest,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Scan QR → tampilkan detail penerima + status bulan ini.

    Tidak membuat record distribusi. Gunakan POST /scan/confirm untuk konfirmasi.
    """
    valid, kode_seri, msg = verify_payload(payload.qr_payload)
    if not valid or not kode_seri:
        return ScanPreviewResponse(valid=False, error=f"QR tidak valid: {msg}")

    p = (
        db.query(Penerima)
        .options(selectinload(Penerima.kategori_assoc).selectinload(PenerimaKategori.kategori))
        .filter(Penerima.kode_seri == kode_seri)
        .first()
    )
    if not p:
        return ScanPreviewResponse(
            valid=False,
            error=f"Kode seri '{kode_seri}' tidak terdaftar di sistem",
        )
    return _build_preview(db, p)


# ── Scan: CONFIRM (create distribusi + GPS opsional) ───────────────────────
@router.post("/scan/confirm", response_model=DistribusiOut)
def scan_confirm(
    payload: ScanQRRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_distribusi),
):
    """Konfirmasi terima bantuan dari hasil scan QR.

    - Untuk kategori "Penerima Bulanan": entri bulan berjalan otomatis di-konfirmasi
      (tolak jika sudah dikonfirmasi sebelumnya).
    - Selalu membuat record Distribusi (sebagai jejak audit + nominal/jenis bantuan).
    - GPS koordinat (opsional) disimpan di field keterangan.
    """
    valid, kode_seri, msg = verify_payload(payload.qr_payload)
    if not valid or not kode_seri:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"QR tidak valid: {msg}")

    p = (
        db.query(Penerima)
        .options(selectinload(Penerima.kategori_assoc).selectinload(PenerimaKategori.kategori))
        .filter(Penerima.kode_seri == kode_seri)
        .first()
    )
    if not p:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Kode seri '{kode_seri}' tidak terdaftar di sistem",
        )
    if not p.is_active:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Penerima non-aktif")

    # Cek bulanan: tolak jika sudah terima bulan ini
    now = datetime.utcnow()
    is_bulanan = any(k.nama == NAMA_KATEGORI_BULANAN for k in p.kategori_list)
    bulanan_id = None
    if is_bulanan:
        row = (
            db.query(DistribusiBulanan)
            .filter(
                DistribusiBulanan.penerima_id == p.id,
                DistribusiBulanan.bulan == now.month,
                DistribusiBulanan.tahun == now.year,
            )
            .first()
        )
        if row and row.status == StatusBulanan.SUDAH_DITERIMA:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Penerima sudah menerima bantuan bulan ini",
            )
        bulanan_id = row.id if row else None

    # Susun keterangan + GPS
    keterangan_parts = []
    if payload.keterangan:
        keterangan_parts.append(payload.keterangan)
    if payload.lokasi_lat is not None and payload.lokasi_lng is not None:
        keterangan_parts.append(
            f"GPS:{payload.lokasi_lat:.6f},{payload.lokasi_lng:.6f}"
        )
    keterangan_full = " | ".join(keterangan_parts) or None

    try:
        dist, fraud = create_distribusi(
            db,
            penerima_id=p.id,
            jenis_bantuan=payload.jenis_bantuan,
            nominal=payload.nominal,
            keterangan=keterangan_full,
            petugas=user,
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))

    # Update entri bulanan kalau ada (best-effort: distribusi sudah ter-commit)
    if bulanan_id:
        try:
            konfirmasi_bulanan(db, bulanan_id, user.id)
        except ValueError as e:
            logger.warning(
                "Konfirmasi bulanan gagal untuk dist %s (penerima_id=%d): %s",
                dist.no_seri, p.id, e,
            )

    broadcast_sync("distribusi.scanned", {
        "no_seri": dist.no_seri,
        "penerima_id": dist.penerima_id,
        "status": dist.status.value,
        "fraud": bool(fraud),
    })
    return dist


# ── Backward-compat: /scan tetap ada (alias /scan/confirm) ─────────────────
@router.post("/scan", response_model=DistribusiOut)
def scan_and_distribute(
    payload: ScanQRRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_distribusi),
):
    """Alias backward-compat untuk POST /scan/confirm."""
    return scan_confirm(payload, db, user)
