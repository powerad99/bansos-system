"""Migrasi: buat tabel distribusi_sosial + seed permission baru."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.database import Base, engine, SessionLocal
from app.models import distribusi_sosial  # noqa: F401 — register model
from app.seeds.seed_kategori import seed_permissions

Base.metadata.create_all(bind=engine)
print("Table distribusi_sosial: OK")

with SessionLocal() as db:
    n = seed_permissions(db)
    print(f"Permissions seeded: {n} baru")

print("Migrasi selesai.")
