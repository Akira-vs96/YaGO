"""Database connection and strictly sequential SQL migrations."""
import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

load_dotenv(Path(__file__).resolve().parents[2] / ".env")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://yago:yago@localhost:5432/yago")
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations"


def get_db():
    with SessionLocal() as db:
        yield db


def migrate():
    """Apply additive versions under a transaction lock; require a backup for upgrades."""
    with engine.begin() as connection:
        connection.execute(text("SELECT pg_advisory_xact_lock(973601)"))
        has_versions = connection.scalar(text("SELECT to_regclass('public.schema_versions') IS NOT NULL"))
        if not has_versions:
            has_product_tables = connection.scalar(text("""SELECT EXISTS(
                SELECT 1 FROM pg_tables WHERE schemaname='public'
                AND tablename <> 'spatial_ref_sys')"""))
            if has_product_tables:
                raise RuntimeError("Unversioned database detected. Back it up and migrate manually; automatic reset is forbidden.")
            with connection.connection.cursor() as cursor:
                cursor.execute((MIGRATIONS / "001_er_model.sql").read_text(), prepare=False)
        version = connection.scalar(text("SELECT max(version) FROM schema_versions")) or 0
        if version < 2:
            raise RuntimeError("Incomplete schema version history. Back up and inspect the database before upgrading.")
        if version < 7:
            populated = connection.scalar(text("SELECT EXISTS(SELECT 1 FROM users LIMIT 1)"))
            if populated and os.getenv("BACKUP_CONFIRMED") != "1":
                raise RuntimeError("Database contains data. Run pg_dump, then set BACKUP_CONFIRMED=1 before upgrading.")
            for target, filename in ((3, "002_product.sql"), (4, "003_integrity.sql"),
                                     (5, "004_education.sql"), (6, "005_order_facts.sql"),
                                     (7, "006_week09_10.sql")):
                if version < target:
                    with connection.connection.cursor() as cursor:
                        cursor.execute((MIGRATIONS / filename).read_text(), prepare=False)


def row_dict(row):
    if row is None:
        return None
    return dict(row._mapping)
