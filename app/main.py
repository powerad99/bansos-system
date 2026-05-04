"""FastAPI application factory + lifespan.

Run dev:   uvicorn app.main:app --reload
Run prod:  uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import Base, SessionLocal, engine
from app.routers import auth, database_bip, distribusi, distribusi_bulanan, distribusi_sosial, fraud, kategori, laporan, ocr, penerima, qr, statistik, users, ws
from app.seeds.seed_kategori import run_all_seeds

# Import models supaya Base.metadata terisi
from app import models  # noqa: F401

logging.basicConfig(
    level=logging.INFO if not settings.DEBUG else logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("bansos")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting %s (env=%s)", settings.APP_NAME, settings.APP_ENV)
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("Tables OK")
    except Exception as e:
        logger.error("Failed to create tables: %s", e)

    # Seed kategori default + admin
    try:
        with SessionLocal() as db:
            run_all_seeds(db)
    except Exception as e:
        logger.error("Seed failed: %s", e)

    yield

    # Shutdown
    logger.info("Shutting down %s", settings.APP_NAME)


app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    description=(
        "Sistem distribusi bantuan sosial dengan AI priority scoring, "
        "anti-fraud detection (RapidFuzz), OCR KTP otomatis, dan QR scanner."
    ),
    lifespan=lifespan,
)


# Static files
import os
_static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
if os.path.isdir(_static_dir):
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")


# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-QR-Payload", "Content-Disposition"],
)


# === Routers ===
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(kategori.router)
app.include_router(penerima.router)
app.include_router(distribusi.router)
app.include_router(distribusi_bulanan.router)
app.include_router(distribusi_sosial.router)
app.include_router(ocr.router)
app.include_router(qr.router)         # /qr/{id}, /scan
app.include_router(fraud.router)
app.include_router(laporan.router)
app.include_router(database_bip.router)
app.include_router(statistik.router)
app.include_router(ws.router)         # /ws


# === Health & root ===
@app.get("/dashboard", tags=["meta"], include_in_schema=False)
def dashboard():
    return FileResponse(os.path.join(_static_dir, "dashboard.html"))


@app.get("/scan-page", tags=["meta"], include_in_schema=False)
def scan_page():
    """Halaman mobile-friendly untuk scan QR penerima (kamera HP/web)."""
    return FileResponse(os.path.join(_static_dir, "scan.html"))


@app.get("/", tags=["meta"])
def root():
    return {
        "app": settings.APP_NAME,
        "version": "1.0.0",
        "env": settings.APP_ENV,
        "docs": "/docs",
    }


@app.get("/health", tags=["meta"])
def health():
    from app.core.redis_client import redis_client
    db_ok = True
    try:
        with SessionLocal() as db:
            db.execute(__import__("sqlalchemy").text("SELECT 1"))
    except Exception as e:
        logger.warning("DB health failed: %s", e)
        db_ok = False
    return {
        "status": "ok" if db_ok else "degraded",
        "db": db_ok,
        "redis": redis_client.available,
    }


# === Exception handler ringkas (biar response error konsisten) ===
@app.exception_handler(ValueError)
async def value_error_handler(request, exc: ValueError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})
