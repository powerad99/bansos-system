"""Helper umum: generator no_seri, normalisasi string, dll."""
import re
import secrets
import string
from datetime import datetime


def generate_no_seri(prefix: str = "BSN") -> str:
    """Generate nomor seri distribusi: PREFIX-YYYYMMDD-XXXXXX."""
    today = datetime.utcnow().strftime("%Y%m%d")
    rand = "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(6))
    return f"{prefix}-{today}-{rand}"


def normalize_text(s: str) -> str:
    """Normalisasi untuk fuzzy match: lowercase, strip, collapse whitespace."""
    if not s:
        return ""
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def mask_nik(nik: str) -> str:
    """Mask NIK untuk display: 3201xxxxxxxxxx12."""
    if not nik or len(nik) != 16:
        return nik
    return f"{nik[:4]}{'x' * 10}{nik[-2:]}"
