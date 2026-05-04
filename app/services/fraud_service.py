"""Fraud Detection Service.

Cek tiga hal saat penerima baru didaftarkan / di-update:

1. NIK duplikat (exact match)               -> FraudType.NIK_DUPLICATE
2. Nama mirip   (RapidFuzz token_set_ratio) -> FraudType.NAMA_SIMILAR
3. Alamat mirip (RapidFuzz token_set_ratio) -> FraudType.ALAMAT_SIMILAR

Kalau (2) dan (3) sama-sama high score terhadap penerima yang sama:
   -> FraudType.COMBO_SIMILAR (more dangerous)

Hasil: kalau ada match >= threshold, set fraud_flag=True dan tulis FraudLog.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple

from rapidfuzz import fuzz, process
from sqlalchemy.orm import Session

from app.config import settings
from app.models import FraudLog, FraudType, Penerima
from app.utils.helpers import normalize_text

logger = logging.getLogger(__name__)


@dataclass
class FraudFinding:
    fraud_type: FraudType
    related_penerima_id: Optional[int]
    similarity: float
    alasan: str
    detail: str


# ============================================================
# Helpers
# ============================================================

def _check_nik_duplicate(
    db: Session, nik: str, exclude_id: Optional[int] = None
) -> Optional[Penerima]:
    q = db.query(Penerima).filter(Penerima.nik == nik)
    if exclude_id is not None:
        q = q.filter(Penerima.id != exclude_id)
    return q.first()


def _fuzzy_best_match(
    target: str,
    candidates: List[Tuple[int, str]],
) -> Optional[Tuple[int, float]]:
    """Cari best fuzzy match dari list (id, text). Return (id, score)."""
    if not target or not candidates:
        return None
    target_n = normalize_text(target)
    if not target_n:
        return None

    # process.extractOne mengharapkan dict-like, kita pakai list dgn key fn
    choices = {pid: normalize_text(txt) for pid, txt in candidates}
    if not any(choices.values()):
        return None

    best = process.extractOne(target_n, choices, scorer=fuzz.token_set_ratio)
    if best is None:
        return None
    # extractOne return (matched_value, score, key)
    _, score, key = best
    return key, float(score)


# ============================================================
# Public API
# ============================================================

def detect_fraud(
    db: Session,
    penerima: Penerima,
    *,
    nama_threshold: Optional[int] = None,
    alamat_threshold: Optional[int] = None,
) -> List[FraudFinding]:
    """Jalankan cek anti-fraud untuk satu penerima (sudah di-DB / belum).

    NOTE: penerima.id boleh None (saat masih create). Yang penting nik/nama/alamat ada.
    Function ini TIDAK menulis ke DB - caller yang persist FraudLog.
    """
    nama_th = nama_threshold or settings.FUZZY_NAMA_THRESHOLD
    alamat_th = alamat_threshold or settings.FUZZY_ALAMAT_THRESHOLD

    findings: List[FraudFinding] = []

    # --- 1. NIK duplikat ---
    if penerima.nik:
        dup = _check_nik_duplicate(db, penerima.nik, exclude_id=penerima.id)
        if dup is not None:
            findings.append(
                FraudFinding(
                    fraud_type=FraudType.NIK_DUPLICATE,
                    related_penerima_id=dup.id,
                    similarity=100.0,
                    alasan=f"NIK {penerima.nik} sudah terdaftar atas nama {dup.nama}",
                    detail=f"existing_id={dup.id}, existing_nama={dup.nama}",
                )
            )

    # --- 2 & 3. Fuzzy nama & alamat ---
    others_q = db.query(Penerima.id, Penerima.nama, Penerima.alamat)
    if penerima.id is not None:
        others_q = others_q.filter(Penerima.id != penerima.id)
    others = others_q.all()

    nama_candidates = [(p.id, p.nama) for p in others]
    alamat_candidates = [(p.id, p.alamat) for p in others]

    nama_match = _fuzzy_best_match(penerima.nama or "", nama_candidates)
    alamat_match = _fuzzy_best_match(penerima.alamat or "", alamat_candidates)

    nama_hit = nama_match if (nama_match and nama_match[1] >= nama_th) else None
    alamat_hit = alamat_match if (alamat_match and alamat_match[1] >= alamat_th) else None

    # Combo: nama & alamat sama-sama mirip ke penerima yg sama -> sangat mencurigakan
    if nama_hit and alamat_hit and nama_hit[0] == alamat_hit[0]:
        combo_score = (nama_hit[1] + alamat_hit[1]) / 2
        findings.append(
            FraudFinding(
                fraud_type=FraudType.COMBO_SIMILAR,
                related_penerima_id=nama_hit[0],
                similarity=combo_score,
                alasan=(
                    f"Nama & alamat sangat mirip dengan penerima id={nama_hit[0]} "
                    f"(nama_score={nama_hit[1]:.1f}, alamat_score={alamat_hit[1]:.1f})"
                ),
                detail=f"nama_score={nama_hit[1]:.2f}; alamat_score={alamat_hit[1]:.2f}",
            )
        )
    else:
        if nama_hit:
            findings.append(
                FraudFinding(
                    fraud_type=FraudType.NAMA_SIMILAR,
                    related_penerima_id=nama_hit[0],
                    similarity=nama_hit[1],
                    alasan=f"Nama mirip dengan penerima id={nama_hit[0]} (score={nama_hit[1]:.1f})",
                    detail=f"threshold={nama_th}",
                )
            )
        if alamat_hit:
            findings.append(
                FraudFinding(
                    fraud_type=FraudType.ALAMAT_SIMILAR,
                    related_penerima_id=alamat_hit[0],
                    similarity=alamat_hit[1],
                    alasan=f"Alamat mirip dengan penerima id={alamat_hit[0]} (score={alamat_hit[1]:.1f})",
                    detail=f"threshold={alamat_th}",
                )
            )

    return findings


def apply_fraud_findings(
    db: Session,
    penerima: Penerima,
    findings: List[FraudFinding],
) -> bool:
    """Persist findings ke fraud_logs + set fraud_flag pada penerima.

    Return True kalau ada findings (= flagged), False kalau bersih.
    """
    if not findings:
        penerima.fraud_flag = False
        penerima.fraud_reason = None
        return False

    penerima.fraud_flag = True
    penerima.fraud_reason = "; ".join(f.alasan for f in findings)

    for f in findings:
        log = FraudLog(
            penerima_id=penerima.id,
            related_penerima_id=f.related_penerima_id,
            fraud_type=f.fraud_type,
            similarity_score=f.similarity,
            alasan=f.alasan,
            detail=f.detail,
        )
        db.add(log)

    logger.warning(
        "Fraud detected for penerima_id=%s nik=%s -> %d finding(s)",
        penerima.id, penerima.nik, len(findings),
    )
    return True


def check_double_distribusi(
    db: Session, penerima_id: int, jenis_bantuan: str, window_days: int = 30
) -> Optional[FraudFinding]:
    """Cek kalau penerima sama menerima jenis bantuan sama dalam window pendek."""
    from datetime import datetime, timedelta

    from app.models import Distribusi

    cutoff = datetime.utcnow() - timedelta(days=window_days)
    existing = (
        db.query(Distribusi)
        .filter(
            Distribusi.penerima_id == penerima_id,
            Distribusi.jenis_bantuan == jenis_bantuan,
            Distribusi.tanggal_distribusi >= cutoff,
        )
        .first()
    )
    if existing:
        return FraudFinding(
            fraud_type=FraudType.DOUBLE_DISTRIBUSI,
            related_penerima_id=penerima_id,
            similarity=100.0,
            alasan=(
                f"Penerima sudah menerima '{jenis_bantuan}' pada "
                f"{existing.tanggal_distribusi.isoformat()} (no_seri={existing.no_seri})"
            ),
            detail=f"window_days={window_days}",
        )
    return None
