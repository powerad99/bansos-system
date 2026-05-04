"""AI Priority Scoring.

Skor prioritas penerima bantuan dihitung dari beberapa komponen yang
masing-masing dinormalisasi ke [0..1], lalu di-aggregate dengan bobot:

    priority_score = (
        W_KAT * kategori_weight       # 0.40 - bobot kategori (multi-kategori -> max)
      + W_INC * income_factor          # 0.25 - semakin miskin semakin tinggi
      + W_DEP * dependent_factor       # 0.20 - semakin banyak tanggungan semakin tinggi
      + W_HIS * history_factor         # 0.15 - belum pernah dapat bantuan -> tinggi
    )

Output:
    score (float 0..1)
    level: HIGH (>=0.75) | MEDIUM (>=0.45) | LOW (<0.45)

Catatan desain:
- Pakai max(weight) dari kategori yg dimiliki, BUKAN sum/avg.
  Alasan: kalau seseorang tergolong "Fakir Miskin" (1.0) DAN "Disabilitas" (0.9),
  prioritas tetap mengikuti kategori paling kritis -> 1.0, bukan rata-rata 0.95.
- Income di-normalize dengan kurva linear di bawah threshold UMP.
- History factor: dihitung dari jumlah distribusi 90 hari terakhir.
  Penerima yang sudah sering dibantu di-de-prioritize agar bantuan menyebar.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Iterable, Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.models import Distribusi, Kategori, Penerima, PriorityLevel

logger = logging.getLogger(__name__)


# ====== Bobot komponen ======
W_KATEGORI = 0.40
W_INCOME = 0.25
W_DEPENDENT = 0.20
W_HISTORY = 0.15

# ====== Konstanta kalibrasi ======
# Penghasilan dianggap "sangat miskin" kalau di bawah ini (rupiah/bulan)
INCOME_FLOOR = 500_000
# Di atas INCOME_CEIL dianggap tidak butuh bantuan
INCOME_CEIL = 4_500_000

# Jumlah tanggungan -> diskalakan
DEPENDENT_CAP = 8  # 8+ tanggungan dianggap maksimum

# History window
HISTORY_WINDOW_DAYS = 90
HISTORY_CAP = 3  # 3+ kali dapat bantuan dalam window -> faktor 0


# ============================================================
# Komponen-komponen scoring
# ============================================================

def _kategori_factor(kategori_list: Iterable[Kategori]) -> float:
    """Ambil weight tertinggi dari kategori yang dimiliki."""
    weights = [k.weight for k in kategori_list if k and k.is_active]
    if not weights:
        return 0.0
    return max(0.0, min(1.0, max(weights)))


def _income_factor(penghasilan: float) -> float:
    """Lower income -> higher factor.

    penghasilan <= INCOME_FLOOR -> 1.0
    penghasilan >= INCOME_CEIL  -> 0.0
    diantaranya: linear inverse.
    """
    if penghasilan <= INCOME_FLOOR:
        return 1.0
    if penghasilan >= INCOME_CEIL:
        return 0.0
    return 1.0 - (penghasilan - INCOME_FLOOR) / (INCOME_CEIL - INCOME_FLOOR)


def _dependent_factor(jumlah_tanggungan: int) -> float:
    """Lebih banyak tanggungan -> faktor lebih tinggi (capped)."""
    if jumlah_tanggungan <= 0:
        return 0.0
    return min(1.0, jumlah_tanggungan / DEPENDENT_CAP)


def _history_factor(distribusi_count_recent: int) -> float:
    """Belum pernah dibantu -> 1.0; sering dibantu -> 0.0.

    Tujuannya: ratain distribusi.
    """
    if distribusi_count_recent <= 0:
        return 1.0
    if distribusi_count_recent >= HISTORY_CAP:
        return 0.0
    return 1.0 - (distribusi_count_recent / HISTORY_CAP)


def _level_from_score(score: float) -> PriorityLevel:
    if score >= settings.PRIORITY_HIGH_THRESHOLD:
        return PriorityLevel.HIGH
    if score >= settings.PRIORITY_MEDIUM_THRESHOLD:
        return PriorityLevel.MEDIUM
    return PriorityLevel.LOW


# ============================================================
# Public API
# ============================================================

def calculate_priority(
    penerima: Penerima,
    db: Optional[Session] = None,
) -> tuple[float, PriorityLevel]:
    """Hitung priority_score & level untuk satu penerima.

    Args:
        penerima: object Penerima (sudah loaded relationships kategori_assoc)
        db: optional Session - kalau diberikan, history factor dihitung dari DB.

    Returns:
        (score: float, level: PriorityLevel)
    """
    # 1. Kategori
    kategori_list = [pk.kategori for pk in (penerima.kategori_assoc or [])]
    kat = _kategori_factor(kategori_list)

    # 2. Income
    inc = _income_factor(penerima.penghasilan or 0.0)

    # 3. Dependents
    dep = _dependent_factor(penerima.jumlah_tanggungan or 0)

    # 4. History
    hist_count = 0
    if db is not None and penerima.id is not None:
        cutoff = datetime.utcnow() - timedelta(days=HISTORY_WINDOW_DAYS)
        hist_count = (
            db.query(Distribusi)
            .filter(
                Distribusi.penerima_id == penerima.id,
                Distribusi.tanggal_distribusi >= cutoff,
            )
            .count()
        )
    hist = _history_factor(hist_count)

    score = (
        W_KATEGORI * kat
        + W_INCOME * inc
        + W_DEPENDENT * dep
        + W_HISTORY * hist
    )
    score = max(0.0, min(1.0, round(score, 4)))
    level = _level_from_score(score)

    logger.debug(
        "Priority for %s: kat=%.2f inc=%.2f dep=%.2f hist=%.2f -> %.4f (%s)",
        getattr(penerima, "nik", "?"), kat, inc, dep, hist, score, level.value,
    )
    return score, level


def update_priority(penerima: Penerima, db: Session) -> Penerima:
    """Hitung & assign priority_score + priority_level ke object (TIDAK commit)."""
    score, level = calculate_priority(penerima, db)
    penerima.priority_score = score
    penerima.priority_level = level
    return penerima


def recalculate_all(db: Session) -> int:
    """Recalculate semua penerima aktif. Return jumlah yang di-update."""
    rows = db.query(Penerima).filter(Penerima.is_active.is_(True)).all()
    for p in rows:
        update_priority(p, db)
    db.commit()
    return len(rows)
