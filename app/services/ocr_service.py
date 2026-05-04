"""OCR Service untuk KTP Indonesia.

Pipeline:
    image (bytes/np.ndarray)
        -> preprocess (OpenCV: resize, grayscale, denoise, threshold)
        -> OCR engine (Tesseract default; PaddleOCR optional)
        -> raw_text
        -> regex parse (utils.regex_ktp.parse_ktp_text)
        -> dict terstruktur

Engine ditentukan oleh settings.OCR_ENGINE: "tesseract" | "paddle".
PaddleOCR di-import lazy supaya tidak memberatkan startup kalau tidak dipakai.
"""
from __future__ import annotations

import io
import logging
from typing import Dict, Optional, Tuple

import cv2
import numpy as np
from PIL import Image

from app.config import settings
from app.utils.regex_ktp import parse_ktp_text

logger = logging.getLogger(__name__)


# ============================================================
# Image loading & preprocessing
# ============================================================

def _bytes_to_cv(image_bytes: bytes) -> np.ndarray:
    """Decode bytes -> BGR ndarray."""
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        # fallback via PIL (handle TIFF / weird formats)
        pil = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        img = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
    return img


def preprocess_ktp(img: np.ndarray) -> np.ndarray:
    """Standard preprocessing untuk KTP scan.

    Steps:
    1. Upscale kalau kekecilan (target lebar >= 1000 px)
    2. Konversi grayscale
    3. Bilateral filter (denoise tapi tetap tajam)
    4. Adaptive threshold + sedikit morphology
    """
    h, w = img.shape[:2]
    if w < 1000:
        scale = 1000 / w
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_CUBIC)

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.bilateralFilter(gray, 9, 75, 75)

    # Adaptive threshold lebih robust ke pencahayaan tidak rata
    thresh = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 15
    )
    # Morph open buat hilangin noise titik kecil
    kernel = np.ones((1, 1), np.uint8)
    cleaned = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel)
    return cleaned


# ============================================================
# OCR engines
# ============================================================

def _ocr_tesseract(img: np.ndarray) -> Tuple[str, float]:
    """Run pytesseract, return (text, avg_confidence_0_1)."""
    import pytesseract

    if settings.TESSERACT_CMD:
        pytesseract.pytesseract.tesseract_cmd = settings.TESSERACT_CMD

    config = "--oem 3 --psm 6"  # PSM 6 = block of text uniform
    try:
        text = pytesseract.image_to_string(img, lang=settings.TESSERACT_LANG, config=config)
        # Confidence dari image_to_data
        data = pytesseract.image_to_data(
            img, lang=settings.TESSERACT_LANG, config=config,
            output_type=pytesseract.Output.DICT,
        )
        confs = [int(c) for c in data.get("conf", []) if str(c).lstrip("-").isdigit() and int(c) >= 0]
        avg = (sum(confs) / len(confs) / 100.0) if confs else 0.0
        return text, avg
    except Exception as e:
        logger.error("Tesseract OCR failed: %s", e)
        return "", 0.0


def _ocr_paddle(img: np.ndarray) -> Tuple[str, float]:
    """Run PaddleOCR. Lazy import - hanya kalau benar-benar dipakai."""
    try:
        from paddleocr import PaddleOCR  # type: ignore
    except ImportError:
        logger.error("PaddleOCR not installed - fallback ke tesseract")
        return _ocr_tesseract(img)

    # Cache instance via module-level attr (PaddleOCR berat di-init)
    global _paddle_instance
    try:
        _paddle_instance  # type: ignore[name-defined]
    except NameError:
        _paddle_instance = PaddleOCR(use_angle_cls=True, lang="en")  # noqa: F841

    try:
        result = _paddle_instance.ocr(img, cls=True)  # type: ignore[name-defined]
        lines, confs = [], []
        for page in result or []:
            for line in page or []:
                if not line or len(line) < 2:
                    continue
                txt, score = line[1][0], line[1][1]
                lines.append(txt)
                confs.append(float(score))
        text = "\n".join(lines)
        avg = sum(confs) / len(confs) if confs else 0.0
        return text, avg
    except Exception as e:
        logger.error("PaddleOCR failed: %s", e)
        return "", 0.0


def run_ocr(img: np.ndarray) -> Tuple[str, float]:
    engine = (settings.OCR_ENGINE or "tesseract").lower()
    if engine == "paddle":
        return _ocr_paddle(img)
    return _ocr_tesseract(img)


# ============================================================
# Public API
# ============================================================

def ocr_ktp_from_bytes(image_bytes: bytes) -> Dict[str, Optional[str]]:
    """Pipeline lengkap: bytes -> dict field KTP + raw_text + confidence."""
    img = _bytes_to_cv(image_bytes)
    pre = preprocess_ktp(img)
    raw_text, conf = run_ocr(pre)

    parsed = parse_ktp_text(raw_text)
    parsed["raw_text"] = raw_text
    parsed["confidence"] = round(conf, 4)
    return parsed
