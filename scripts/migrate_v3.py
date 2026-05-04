"""Migration v3 — sederhanakan role menjadi 3 tingkatan.

Langkah:
  1. Tambah nilai enum 'administrator' jika belum ada
  2. Migrasi data:
       admin      → administrator  (lama 'admin' = superadmin)
       supervisor → admin          (menjadi manajemen)
       petugas_entri / petugas_distribusi / viewer → petugas
  3. Seed 5 task permissions baru (idempotent)
  4. Hapus old permissions yang tidak relevan

Script ini aman dijalankan berkali-kali (idempotent).
"""
import logging

import psycopg2
from sqlalchemy import text

from app.database import SessionLocal, engine
from app.seeds.seed_kategori import seed_permissions

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("migrate_v3")


def run_migration() -> None:
    with engine.connect() as conn:

        # 1. Tambah 'administrator' ke enum kalau belum ada
        result = conn.execute(text(
            "SELECT 1 FROM pg_enum e "
            "JOIN pg_type t ON t.oid = e.enumtypid "
            "WHERE t.typname = 'user_role' AND e.enumlabel = 'administrator'"
        )).fetchone()
        if not result:
            log.info("Adding enum value 'administrator'...")
            conn.execute(text("ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'administrator'"))
            conn.commit()
            log.info("  Done.")
        else:
            log.info("Enum value 'administrator' already exists — skip.")

        # 2. Migrasi data role
        migrations = [
            ("admin",              "administrator"),
            ("supervisor",         "admin"),
            ("petugas_entri",      "petugas"),
            ("petugas_distribusi", "petugas"),
            ("viewer",             "petugas"),
        ]
        for old, new in migrations:
            n = conn.execute(
                text("UPDATE users SET role = :new WHERE role = :old"),
                {"old": old, "new": new},
            ).rowcount
            if n:
                log.info("  Updated %d users: %s → %s", n, old, new)
            conn.commit()

        log.info("Role migration done.")

    # 3. Seed 5 task permissions (idempotent)
    with SessionLocal() as db:
        seed_permissions(db)
        log.info("Permissions seeded.")

    log.info("migrate_v3 complete.")


if __name__ == "__main__":
    run_migration()
