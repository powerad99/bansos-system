"""Parser teks OCR KTP -> dict field terstruktur.

KTP Indonesia umumnya punya layout:
    PROVINSI ...
    KABUPATEN ...
    NIK : 3201XXXXXXXXXXXX
    Nama : BUDI SANTOSO
    Tempat/Tgl Lahir : JAKARTA, 17-08-1990
    Jenis Kelamin : LAKI-LAKI
    Alamat : JL MERDEKA NO 10
    RT/RW : 001/002
    Kel/Desa : SUKAJAYA
    Kecamatan : CIBINONG
    Agama : ISLAM
    Status Perkawinan : KAWIN
    Pekerjaan : KARYAWAN SWASTA

OCR sering noisy -> regex kita harus tolerant terhadap typo umum.
"""
import re
from typing import Dict, Optional


# === Regex patterns ===
NIK_RE = re.compile(r"\b(\d{16})\b")

# "Nama" + (titik dua / spasi / dash) + value sampai newline
NAMA_RE = re.compile(
    r"Nama\s*[:\-]?\s*([A-Z][A-Z .,'`\-]{2,})", re.IGNORECASE
)

# TTL: kota, dd-mm-yyyy
TTL_RE = re.compile(
    r"(?:Tempat\s*/?\s*Tgl\s*Lahir|TTL)\s*[:\-]?\s*"
    r"([A-Z][A-Z .'\-]+?)\s*[,]\s*"
    r"(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})",
    re.IGNORECASE,
)

JK_RE = re.compile(r"Jenis\s*Kelamin\s*[:\-]?\s*(LAKI[\- ]?LAKI|PEREMPUAN)", re.IGNORECASE)

ALAMAT_RE = re.compile(r"Alamat\s*[:\-]?\s*([A-Z0-9 .,'`/\-]{3,})", re.IGNORECASE)

RT_RW_RE = re.compile(r"RT\s*/?\s*RW\s*[:\-]?\s*(\d{1,3}\s*/\s*\d{1,3})", re.IGNORECASE)

KEL_RE = re.compile(r"(?:Kel(?:urahan)?|Desa)\s*[:\-]?\s*([A-Z][A-Z .'\-]{2,})", re.IGNORECASE)
KEC_RE = re.compile(r"Kecamatan\s*[:\-]?\s*([A-Z][A-Z .'\-]{2,})", re.IGNORECASE)
AGAMA_RE = re.compile(r"Agama\s*[:\-]?\s*([A-Z]{3,15})", re.IGNORECASE)
STATUS_RE = re.compile(
    r"Status\s*Perkawinan\s*[:\-]?\s*(BELUM\s+KAWIN|KAWIN|CERAI\s+\w+)", re.IGNORECASE
)
KERJA_RE = re.compile(r"Pekerjaan\s*[:\-]?\s*([A-Z][A-Z /\-]{2,})", re.IGNORECASE)


def _clean(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    s = re.sub(r"\s+", " ", s).strip(" :-.,")
    return s or None


def parse_ktp_text(text: str) -> Dict[str, Optional[str]]:
    """Ekstrak field dari raw text OCR KTP.

    Return dict dengan key: nik, nama, tempat_lahir, tanggal_lahir,
    jenis_kelamin, alamat, rt_rw, kelurahan, kecamatan, agama,
    status_perkawinan, pekerjaan.
    """
    if not text:
        return {}

    # Normalisasi karakter mirip yang sering bikin OCR error
    norm = (
        text.replace("|", "I")
        .replace("0", "0")  # placeholder; bisa diganti rule lebih agresif
        .replace("\u00a0", " ")
    )

    result: Dict[str, Optional[str]] = {
        "nik": None,
        "nama": None,
        "tempat_lahir": None,
        "tanggal_lahir": None,
        "jenis_kelamin": None,
        "alamat": None,
        "rt_rw": None,
        "kelurahan": None,
        "kecamatan": None,
        "agama": None,
        "status_perkawinan": None,
        "pekerjaan": None,
    }

    if m := NIK_RE.search(norm):
        result["nik"] = m.group(1)

    if m := NAMA_RE.search(norm):
        result["nama"] = _clean(m.group(1))

    if m := TTL_RE.search(norm):
        result["tempat_lahir"] = _clean(m.group(1))
        result["tanggal_lahir"] = _clean(m.group(2))

    if m := JK_RE.search(norm):
        jk_raw = m.group(1).upper().replace(" ", "").replace("-", "")
        result["jenis_kelamin"] = "L" if "LAKI" in jk_raw else "P"

    if m := ALAMAT_RE.search(norm):
        # Cut alamat di newline pertama supaya tidak nyangkut ke RT/RW
        val = m.group(1).split("\n")[0]
        result["alamat"] = _clean(val)

    if m := RT_RW_RE.search(norm):
        result["rt_rw"] = re.sub(r"\s+", "", m.group(1))

    if m := KEL_RE.search(norm):
        result["kelurahan"] = _clean(m.group(1))
    if m := KEC_RE.search(norm):
        result["kecamatan"] = _clean(m.group(1))
    if m := AGAMA_RE.search(norm):
        result["agama"] = _clean(m.group(1))
    if m := STATUS_RE.search(norm):
        result["status_perkawinan"] = _clean(m.group(1).upper())
    if m := KERJA_RE.search(norm):
        result["pekerjaan"] = _clean(m.group(1))

    return result
