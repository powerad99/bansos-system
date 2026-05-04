# 🏥 Bansos Distribution System

Sistem distribusi bantuan sosial **production-grade** berbasis Python:
**FastAPI + SQLAlchemy + PostgreSQL + Redis** dengan fitur:

- 🧠 **AI Priority Scoring** (HIGH/MEDIUM/LOW) berdasarkan kategori, penghasilan, tanggungan, dan riwayat distribusi.
- 🛡️ **Anti-Fraud Detection** dengan RapidFuzz (NIK duplikat, nama mirip, alamat mirip, double-distribusi).
- 📷 **OCR KTP otomatis** (OpenCV + Tesseract; PaddleOCR optional).
- 🔳 **QR generator + scanner ber-tanda-tangan** (HMAC-SHA256, anti-tamper).
- 🔌 **WebSocket realtime** untuk event distribusi & fraud.
- 📊 **Statistik per kategori** + **Export Excel**.
- 🔐 JWT auth + role-based access (ADMIN / PETUGAS / VIEWER).

---

## 📁 Struktur Project

```
bansos-system/
├── app/
│   ├── main.py                 # FastAPI app + lifespan + CORS
│   ├── config.py               # Settings (pydantic-settings)
│   ├── database.py             # SQLAlchemy engine + session
│   ├── dependencies.py         # Auth deps & role-guard
│   │
│   ├── models/                 # 🧱 SQLAlchemy ORM
│   │   ├── user.py
│   │   ├── kategori.py
│   │   ├── penerima.py
│   │   ├── penerima_kategori.py
│   │   ├── distribusi.py
│   │   └── fraud_log.py
│   │
│   ├── schemas/                # 📦 Pydantic v2 schemas
│   ├── routers/                # 🌐 FastAPI routers
│   │   ├── auth.py             # /auth/login, /auth/register
│   │   ├── kategori.py         # /kategori (CRUD, default tidak boleh dihapus)
│   │   ├── penerima.py         # /penerima (CRUD + filter + export)
│   │   ├── distribusi.py       # /distribusi (+ export)
│   │   ├── ocr.py              # /ocr/ktp
│   │   ├── qr.py               # /qr/{id}, /scan
│   │   ├── fraud.py            # /fraud
│   │   ├── statistik.py        # /statistik
│   │   └── ws.py               # /ws  (WebSocket realtime)
│   │
│   ├── services/               # 🧠 Business logic
│   │   ├── priority_service.py # 🟢 AI scoring (calculate_priority)
│   │   ├── fraud_service.py    # 🔴 RapidFuzz fraud detection
│   │   ├── ocr_service.py      # 📷 OpenCV + Tesseract / PaddleOCR
│   │   ├── qr_service.py       # 🔳 Signed QR generator + verifier
│   │   ├── distribusi_service.py
│   │   ├── auth_service.py
│   │   └── export_service.py   # Excel export (openpyxl)
│   │
│   ├── core/
│   │   ├── security.py         # JWT + bcrypt
│   │   ├── redis_client.py     # Redis client (graceful offline)
│   │   └── ws_manager.py       # WebSocket connection manager
│   │
│   ├── seeds/
│   │   └── seed_kategori.py    # 4 kategori default + admin user
│   │
│   └── utils/
│       ├── helpers.py          # generate_no_seri, normalize_text
│       └── regex_ktp.py        # Parser teks OCR KTP -> dict
│
├── scripts/
│   └── init_db.py              # python -m scripts.init_db
│
├── tests/
│   └── test_priority.py        # Unit test scoring + QR + regex KTP
│
├── docker-compose.yml          # Postgres 16 + Redis 7
├── requirements.txt
├── .env.example
├── run.sh                      # One-shot: venv + deps + init + uvicorn
└── README.md
```

---

## 🚀 Cara Run

### Opsi A — Cepat (Docker untuk DB, Python lokal untuk app)

```bash
# 1. Jalankan Postgres + Redis
docker compose up -d

# 2. Setup Python env
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3. Copy env & edit kalau perlu
cp .env.example .env

# 4. Init DB + seed (kategori default + admin user)
python -m scripts.init_db

# 5. Run dev server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Opsi B — Sekali jalan

```bash
chmod +x run.sh
./run.sh
```

> ⚠️ **Wajib install Tesseract** di sistem (untuk OCR):
>
> - Ubuntu/Debian: `sudo apt-get install -y tesseract-ocr tesseract-ocr-ind`
> - macOS: `brew install tesseract tesseract-lang`
> - Windows: download installer UB-Mannheim, lalu set `TESSERACT_CMD` di `.env`.
>
> Cek: `tesseract --version`

Buka **http://localhost:8000/docs** untuk Swagger UI lengkap.

### Default credentials

```
username : admin
password : admin123
```

> 🚨 **GANTI di produksi!**

---

## 🧠 AI Priority Scoring

Lokasi: `app/services/priority_service.py` → `calculate_priority(penerima, db)`.

```
priority_score = 0.40·kategori + 0.25·income + 0.20·dependent + 0.15·history
```

| Komponen | Cara hitung |
|---|---|
| `kategori`  | `max(weight)` antar kategori (multi-kategori → ambil paling kritis) |
| `income`    | linear inverse: `≤500K → 1.0`, `≥4.5jt → 0.0` |
| `dependent` | `min(jumlah_tanggungan / 8, 1.0)` |
| `history`   | belum dapat bantuan 90 hari → `1.0`; ≥3× → `0.0` (de-prioritize agar bantuan menyebar) |

Output level:

| Score | Level |
|---|---|
| ≥ 0.75 | **HIGH**   |
| ≥ 0.45 | **MEDIUM** |
| < 0.45 | **LOW**    |

Threshold bisa di-tune via `.env` (`PRIORITY_HIGH_THRESHOLD`, `PRIORITY_MEDIUM_THRESHOLD`).

---

## 🛡️ Fraud Detection

Lokasi: `app/services/fraud_service.py`. Auto-jalan setiap **CREATE / UPDATE penerima**.

| Tipe | Cara deteksi |
|---|---|
| `NIK_DUPLICATE`    | exact match NIK existing |
| `NAMA_SIMILAR`     | RapidFuzz `token_set_ratio` ≥ `FUZZY_NAMA_THRESHOLD` (default 90) |
| `ALAMAT_SIMILAR`   | RapidFuzz ≥ `FUZZY_ALAMAT_THRESHOLD` (default 85) |
| `COMBO_SIMILAR`    | nama **dan** alamat sama-sama mirip ke penerima yang **sama** |
| `DOUBLE_DISTRIBUSI`| jenis bantuan sama, penerima sama, dalam window 30 hari |

Kalau terdeteksi:
- `penerima.fraud_flag = True`
- `penerima.fraud_reason` di-isi
- Catatan masuk ke tabel `fraud_logs`
- Untuk `DOUBLE_DISTRIBUSI`: distribusi tetap dibuat tapi `status=REJECTED`

---

## 📷 OCR KTP

Pipeline `app/services/ocr_service.py`:

```
bytes → OpenCV(resize, gray, bilateral, adaptive_threshold)
      → Tesseract (default) | PaddleOCR (opsional)
      → regex parser (utils/regex_ktp.py)
      → JSON
```

Field yang diekstrak: `nik, nama, tempat_lahir, tanggal_lahir, jenis_kelamin, alamat, rt_rw, kelurahan, kecamatan, agama, status_perkawinan, pekerjaan` + `raw_text` + `confidence`.

Mau pakai PaddleOCR? Uncomment `paddleocr`/`paddlepaddle` di `requirements.txt`, lalu set `OCR_ENGINE=paddle` di `.env`.

---

## 🔳 QR Code

Format payload: `v1.<penerima_id>.<exp_ts>.<sig>`

`sig` = HMAC-SHA256 dari `v1.<id>.<exp>` pakai `QR_SECRET`, di-truncate 16 char base64url. Anti-tamper: ubah ID → signature gagal verify.

---

## 🔌 Endpoint API

### Auth
| Method | Path | Keterangan |
|---|---|---|
| POST | `/auth/login`     | login → JWT |
| POST | `/auth/register`  | (admin only) bikin user baru |

### Penerima
| Method | Path | Keterangan |
|---|---|---|
| GET    | `/penerima`              | list + filter (`q`, `kategori_id`, `priority`, `fraud_only`) + pagination |
| GET    | `/penerima/{id}`         | detail |
| POST   | `/penerima`              | create (auto AI score + fraud check) |
| PUT    | `/penerima/{id}`         | update (re-score & re-check fraud) |
| DELETE | `/penerima/{id}?hard=false` | soft / hard delete |
| GET    | `/penerima/export/xlsx`  | export Excel |

### Kategori
| Method | Path | Keterangan |
|---|---|---|
| GET    | `/kategori`              | list |
| POST   | `/kategori`              | (admin) tambah kategori baru |
| PUT    | `/kategori/{id}`         | (admin) update |
| DELETE | `/kategori/{id}`         | (admin) hapus — **gagal kalau `is_default=True`** |

### Distribusi
| Method | Path | Keterangan |
|---|---|---|
| POST | `/distribusi`              | create + auto `no_seri` + cek double-distribusi |
| GET  | `/distribusi`              | list + filter status / penerima |
| GET  | `/distribusi/{id}`         | detail |
| GET  | `/distribusi/export/xlsx`  | export Excel |

### OCR
| Method | Path | Keterangan |
|---|---|---|
| POST | `/ocr/ktp` | multipart `file` → JSON field KTP |

### QR
| Method | Path | Keterangan |
|---|---|---|
| GET  | `/qr/{penerima_id}` | PNG QR untuk penerima (header `X-QR-Payload`) |
| POST | `/scan`             | scan QR → buat distribusi otomatis |

### Fraud & Statistik
| Method | Path | Keterangan |
|---|---|---|
| GET | `/fraud`     | list fraud_logs + filter |
| GET | `/statistik` | dashboard overview |

### Realtime
| | | |
|---|---|---|
| WS | `/ws?token=<JWT>` | subscribe event realtime |

---

## 📦 Contoh Request / Response

### 1. Login
```bash
curl -X POST http://localhost:8000/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin123"}'
```
```json
{
  "access_token": "eyJhbGciOi...",
  "token_type": "bearer",
  "expires_in": 3600,
  "user": {"id":1,"username":"admin","role":"admin", "...": "..."}
}
```

### 2. Tambah Penerima (multi-kategori)
```bash
TOKEN=eyJhbGc...
curl -X POST http://localhost:8000/penerima \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{
    "nik": "3201234567890123",
    "nama": "Budi Santoso",
    "alamat": "Jl. Merdeka No. 10, Cibinong",
    "tanggal_lahir": "1980-05-15",
    "jenis_kelamin": "L",
    "penghasilan": 800000,
    "jumlah_tanggungan": 4,
    "kategori_ids": [2, 4]
  }'
```
Response (singkat):
```json
{
  "id": 1, "nik": "3201234567890123", "nama": "Budi Santoso",
  "priority_score": 0.83, "priority_level": "HIGH",
  "fraud_flag": false, "fraud_reason": null,
  "kategori": [
    {"id": 2, "nama": "Fakir Miskin",  "weight": 1.0, "is_default": true},
    {"id": 4, "nama": "Disabilitas",   "weight": 0.9, "is_default": true}
  ]
}
```

### 3. OCR KTP
```bash
curl -X POST http://localhost:8000/ocr/ktp \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@/path/to/ktp.jpg"
```
```json
{
  "nik": "3201234567890123",
  "nama": "BUDI SANTOSO",
  "tempat_lahir": "JAKARTA",
  "tanggal_lahir": "17-08-1990",
  "jenis_kelamin": "L",
  "alamat": "JL MERDEKA NO 10",
  "rt_rw": "001/002",
  "kelurahan": "SUKAJAYA",
  "kecamatan": "CIBINONG",
  "agama": "ISLAM",
  "status_perkawinan": "KAWIN",
  "pekerjaan": "KARYAWAN SWASTA",
  "confidence": 0.91
}
```

### 4. Generate QR Penerima
```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/qr/1 --output qr.png
```
Response: PNG image. Header `X-QR-Payload: v1.1.1791000000.aBcD3fGhIj4kLmNo`.

### 5. Scan QR → Buat Distribusi
```bash
curl -X POST http://localhost:8000/scan \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{
    "qr_payload": "v1.1.1791000000.aBcD3fGhIj4kLmNo",
    "jenis_bantuan": "Sembako Bulan November",
    "nominal": 250000,
    "keterangan": "Distribusi posko RW 02"
  }'
```
```json
{
  "id": 12, "no_seri": "BSN-20261104-X9K2QE",
  "penerima_id": 1, "petugas_id": 1,
  "jenis_bantuan": "Sembako Bulan November",
  "nominal": 250000, "status": "DISTRIBUTED",
  "tanggal_distribusi": "2026-11-04T07:21:33"
}
```

### 6. Statistik
```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/statistik
```
```json
{
  "penerima": {
    "total": 1240, "aktif": 1198, "fraud_flagged": 14,
    "per_priority": {"HIGH": 312, "MEDIUM": 540, "LOW": 388},
    "per_kategori": [
      {"nama": "Fakir Miskin", "jumlah": 612},
      {"nama": "Disabilitas", "jumlah": 188},
      {"nama": "Anak Yatim Piatu", "jumlah": 95},
      {"nama": "Penerima Bulanan", "jumlah": 770}
    ]
  },
  "distribusi": {
    "total": 5420,
    "per_status": {"PENDING": 0, "DISTRIBUTED": 5391, "REJECTED": 29},
    "last_7_days": 184
  },
  "fraud_logs": {"total": 31}
}
```

### 7. Subscribe WebSocket (browser)
```js
const ws = new WebSocket(`ws://localhost:8000/ws?token=${TOKEN}`);
ws.onmessage = (e) => console.log("event:", JSON.parse(e.data));
// {"event":"distribusi.created","data":{...}}
```

---

## 🧪 Testing

```bash
pip install pytest
pytest tests/ -v
```

Test mencakup: AI scoring (HIGH/MEDIUM/LOW + max-weight rule), helper, regex KTP, QR signing roundtrip, dan QR tamper-rejection. Semua **tanpa DB / network**.

---

## 🔒 Production checklist

- [ ] Ganti `SECRET_KEY` & `QR_SECRET` ke nilai random 64 char.
- [ ] Ganti password admin default.
- [ ] Set `DEBUG=false`, `APP_ENV=production`.
- [ ] Pakai reverse proxy (nginx/caddy) + HTTPS.
- [ ] Naikkan worker uvicorn (`--workers 4`) atau pakai gunicorn.
- [ ] Atur backup Postgres (pg_dump terjadwal).
- [ ] Tune fuzzy threshold sesuai kualitas data lapangan.
- [ ] Enable rate limiting (mis. via nginx atau slowapi).

---

## 📝 Lisensi

MIT — gunakan, modifikasi, distribusikan dengan bebas.
