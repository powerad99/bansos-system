"""Fraud endpoints."""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models import FraudLog, FraudType, User
from app.schemas.fraud import FraudListResponse

router = APIRouter(prefix="/fraud", tags=["fraud"])


@router.get("", response_model=FraudListResponse)
def list_fraud(
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    fraud_type: Optional[FraudType] = None,
    penerima_id: Optional[int] = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    q = db.query(FraudLog).order_by(FraudLog.created_at.desc())
    if fraud_type is not None:
        q = q.filter(FraudLog.fraud_type == fraud_type)
    if penerima_id is not None:
        q = q.filter(FraudLog.penerima_id == penerima_id)

    total = q.count()
    rows = q.offset((page - 1) * size).limit(size).all()
    return FraudListResponse(total=total, items=rows)
