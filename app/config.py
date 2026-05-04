"""Konfigurasi aplikasi - dibaca dari env variables / .env."""
from functools import lru_cache
from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # App
    APP_NAME: str = "Bansos Distribution System"
    APP_ENV: str = "development"
    DEBUG: bool = True

    # DB
    DATABASE_URL: str = "postgresql+psycopg2://bansos:bansos123@localhost:5432/bansos_db"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # Security
    SECRET_KEY: str = "change-me-please-change-me-please-change-me"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    ALGORITHM: str = "HS256"

    # QR
    QR_SECRET: str = "qr-secret-default"

    # OCR
    OCR_ENGINE: str = "tesseract"
    TESSERACT_CMD: str = "/usr/bin/tesseract"
    TESSERACT_LANG: str = "ind+eng"

    # Fraud thresholds
    FUZZY_NAMA_THRESHOLD: int = 90
    FUZZY_ALAMAT_THRESHOLD: int = 85

    # Priority thresholds
    PRIORITY_HIGH_THRESHOLD: float = 0.75
    PRIORITY_MEDIUM_THRESHOLD: float = 0.45

    # CORS
    CORS_ORIGINS: List[str] = ["http://localhost:3000", "http://localhost:5173"]

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def split_cors(cls, v):
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        return v

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True, extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
