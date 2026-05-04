"""QR Service.

Payload QR adalah **kode seri penerima** (mis. ``DIS-202604-00004``).
Format dijamin unik di tabel penerima (kolom kode_seri UNIQUE).

Validasi:
  - Format: ``[A-Z]{2,5}-YYYYMM-NNNNN``
  - Eksistensi penerima: dilakukan oleh caller (lookup ke DB by kode_seri).

Tidak ada signing/HMAC — QR adalah identifier publik. Pemalsuan QR cukup
dideteksi dengan: kode tidak cocok dengan record DB, penerima non-aktif,
atau status "sudah terima bulan ini".
"""
from __future__ import annotations

import io
import re
from typing import Optional, Tuple

import qrcode

KODE_SERI_RE = re.compile(r"^[A-Z]{2,5}-\d{6}-\d{4,6}$")


def is_valid_kode_seri(payload: str) -> bool:
    return bool(payload) and bool(KODE_SERI_RE.match(payload.strip()))


def build_payload(kode_seri: str) -> str:
    """Payload QR = kode_seri as-is (string). Validasi format di sini."""
    if not kode_seri:
        raise ValueError("kode_seri kosong — penerima belum punya kode seri")
    if not is_valid_kode_seri(kode_seri):
        raise ValueError(f"Format kode_seri tidak valid: {kode_seri}")
    return kode_seri.strip()


def verify_payload(payload: str) -> Tuple[bool, Optional[str], str]:
    """Validasi format payload QR.

    Return ``(valid, kode_seri_or_none, error_message)``.
    Caller wajib lakukan lookup ke DB untuk memastikan kode_seri terdaftar.
    """
    if not payload:
        return False, None, "Payload kosong"
    p = payload.strip()
    if not KODE_SERI_RE.match(p):
        return False, None, "Format kode seri tidak valid (contoh: DIS-202604-00004)"
    return True, p, "OK"


def generate_qr_png(payload: str, box_size: int = 10, border: int = 4) -> bytes:
    """Render QR ke PNG bytes."""
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=box_size,
        border=border,
    )
    qr.add_data(payload)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def generate_qr_for_kode_seri(kode_seri: str) -> Tuple[str, bytes]:
    """Convenience: return ``(payload, png_bytes)`` dari kode_seri."""
    payload = build_payload(kode_seri)
    return payload, generate_qr_png(payload)
