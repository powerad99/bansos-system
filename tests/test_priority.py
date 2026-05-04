"""Unit test untuk priority scoring & fraud detection.

Test ini TIDAK butuh DB - kita bikin object Penerima dummy.
Run: pytest tests/ -v
"""
from types import SimpleNamespace

from app.models.penerima import PriorityLevel
from app.services import priority_service
from app.utils.helpers import generate_no_seri, normalize_text


def _kat(weight: float, active: bool = True):
    return SimpleNamespace(weight=weight, is_active=active)


def _pk(weight: float):
    return SimpleNamespace(kategori=_kat(weight))


def _penerima(*, kat_weights, penghasilan=0.0, tanggungan=0):
    return SimpleNamespace(
        id=None,
        nik="3201000000000001",
        nama="DUMMY",
        kategori_assoc=[_pk(w) for w in kat_weights],
        penghasilan=penghasilan,
        jumlah_tanggungan=tanggungan,
    )


# -------------------- priority --------------------

def test_priority_high_fakir_miskin_no_income():
    p = _penerima(kat_weights=[1.0], penghasilan=0, tanggungan=5)
    score, lvl = priority_service.calculate_priority(p, db=None)
    assert lvl == PriorityLevel.HIGH
    assert score >= 0.75


def test_priority_low_no_kategori_high_income():
    p = _penerima(kat_weights=[], penghasilan=10_000_000, tanggungan=0)
    score, lvl = priority_service.calculate_priority(p, db=None)
    assert lvl == PriorityLevel.LOW
    assert score < 0.45


def test_priority_uses_max_weight_among_categories():
    # 0.7 + 0.9 -> max() = 0.9, bukan rata-rata
    p1 = _penerima(kat_weights=[0.7, 0.9], penghasilan=1_000_000, tanggungan=2)
    p2 = _penerima(kat_weights=[0.9], penghasilan=1_000_000, tanggungan=2)
    s1, _ = priority_service.calculate_priority(p1, db=None)
    s2, _ = priority_service.calculate_priority(p2, db=None)
    assert abs(s1 - s2) < 1e-6


def test_priority_score_in_unit_interval():
    p = _penerima(kat_weights=[1.0], penghasilan=0, tanggungan=20)
    score, _ = priority_service.calculate_priority(p, db=None)
    assert 0.0 <= score <= 1.0


# -------------------- helpers --------------------

def test_no_seri_format():
    s = generate_no_seri()
    parts = s.split("-")
    assert len(parts) == 3
    assert parts[0] == "BSN"
    assert len(parts[1]) == 8 and parts[1].isdigit()
    assert len(parts[2]) == 6


def test_normalize_text_strips_punct():
    assert normalize_text("  Jl. Merdeka  No.10!! ") == "jl merdeka no 10"
    assert normalize_text("BUDI    Santoso") == "budi santoso"


# -------------------- regex KTP --------------------

def test_parse_ktp_text_basic():
    from app.utils.regex_ktp import parse_ktp_text

    raw = """
    PROVINSI DKI JAKARTA
    NIK : 3201234567890123
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
    """
    out = parse_ktp_text(raw)
    assert out["nik"] == "3201234567890123"
    assert out["nama"] == "BUDI SANTOSO"
    assert out["tempat_lahir"] == "JAKARTA"
    assert out["tanggal_lahir"] == "17-08-1990"
    assert out["jenis_kelamin"] == "L"
    assert out["rt_rw"] == "001/002"
    assert out["agama"] == "ISLAM"


# -------------------- QR (kode seri) --------------------

def test_qr_payload_roundtrip_kode_seri():
    from app.services.qr_service import build_payload, verify_payload

    payload = build_payload("DIS-202604-00004")
    valid, ks, msg = verify_payload(payload)
    assert valid is True
    assert ks == "DIS-202604-00004"
    assert msg == "OK"


def test_qr_invalid_format_rejected():
    from app.services.qr_service import verify_payload

    for bad in ["", "abc", "dis-202604-00004", "DIS_202604_00004", "DIS-2026-00004"]:
        valid, ks, msg = verify_payload(bad)
        assert valid is False, f"harusnya invalid: {bad}"
        assert ks is None
