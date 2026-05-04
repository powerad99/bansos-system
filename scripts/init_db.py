"""Manual init: create tables + seed.

Usage:
    python -m scripts.init_db
"""
import logging

from app.database import Base, SessionLocal, engine
from app import models  # noqa: F401  - register models
from app.seeds.seed_kategori import run_all_seeds

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("init_db")


def main() -> None:
    log.info("Creating tables...")
    Base.metadata.create_all(bind=engine)
    log.info("Tables OK.")

    log.info("Running seeds...")
    with SessionLocal() as db:
        run_all_seeds(db)
    log.info("Seeds OK.")
    log.info("DONE. Default admin: admin / admin123 (GANTI di produksi)")


if __name__ == "__main__":
    main()
