"""Distribusi service - orchestrator scan QR -> create distribusi."""
from __future__ import annotations

import logging
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from app.models import (
    Distribusi,
    DistribusiStatus,
    FraudLog,
    FraudType,
    Penerima,
    User,
)
from app.services.fraud_service import check_double_distribusi
from app.utils.helpers import generate_no_seri

logger = logging.getLogger(__name__)


def create_distribusi(
    db: Session,
    *,
    penerima_id: int,
    jenis_bantuan: str,
    nominal: float,
    keterangan: Optional[str],
    petugas: Optional[User],
    skip_double_check: bool = False,
) -> Tuple[Distribusi, Optional[FraudLog]]:
    """Buat record distribusi + auto-generate no_seri.

    Returns (distribusi, fraud_log_or_None).
    Kalau ditemukan double-distribusi dalam 30 hari, distribusi tetap dibuat
    tapi diberi status REJECTED + dicatat ke fraud_logs.
    """
    penerima = db.query(Penerima).filter(Penerima.id == penerima_id).first()
    if penerima is None:
        raise ValueError(f"Penerima id={penerima_id} tidak ditemukan")
    if not penerima.is_active:
        raise ValueError(f"Penerima id={penerima_id} non-aktif")

    fraud_log: Optional[FraudLog] = None
    status = DistribusiStatus.DISTRIBUTED

    if not skip_double_check:
        finding = check_double_distribusi(db, penerima_id, jenis_bantuan)
        if finding is not None:
            status = DistribusiStatus.REJECTED
            fraud_log = FraudLog(
                penerima_id=penerima_id,
                related_penerima_id=finding.related_penerima_id,
                fraud_type=FraudType.DOUBLE_DISTRIBUSI,
                similarity_score=finding.similarity,
                alasan=finding.alasan,
                detail=finding.detail,
            )
            db.add(fraud_log)
            penerima.fraud_flag = True
            penerima.fraud_reason = finding.alasan

    dist = Distribusi(
        no_seri=generate_no_seri(),
        penerima_id=penerima_id,
        petugas_id=petugas.id if petugas else None,
        jenis_bantuan=jenis_bantuan,
        nominal=nominal,
        keterangan=keterangan,
        status=status,
    )
    db.add(dist)
    db.commit()
    db.refresh(dist)
    if fraud_log:
        db.refresh(fraud_log)

    logger.info(
        "Distribusi created: %s -> penerima_id=%d (status=%s)",
        dist.no_seri, penerima_id, status.value,
    )
    return dist, fraud_log
