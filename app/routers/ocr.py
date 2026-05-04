"""OCR KTP endpoint."""
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.dependencies import require_entri
from app.models import User
from app.schemas.fraud import OCRResult
from app.services.ocr_service import ocr_ktp_from_bytes

router = APIRouter(prefix="/ocr", tags=["ocr"])

ALLOWED_MIME = {"image/jpeg", "image/png", "image/jpg", "image/webp", "image/bmp"}
MAX_BYTES = 8 * 1024 * 1024  # 8 MB


@router.post("/ktp", response_model=OCRResult)
async def ocr_ktp(
    file: UploadFile = File(..., description="Foto/scan KTP"),
    _: User = Depends(require_entri),
):
    if file.content_type not in ALLOWED_MIME:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            f"Format {file.content_type} tidak didukung. Allowed: {sorted(ALLOWED_MIME)}",
        )
    blob = await file.read()
    if len(blob) > MAX_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "File > 8 MB")
    if len(blob) < 1024:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "File terlalu kecil / kosong")

    try:
        parsed = ocr_ktp_from_bytes(blob)
    except Exception as e:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"OCR error: {e}")

    return OCRResult(**parsed)
