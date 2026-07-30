"""One-off script: creates the emp_erp database if it does not already exist."""

import sys
from pathlib import Path
from urllib.parse import urlsplit

import psycopg
from psycopg import sql

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import get_settings


def main() -> None:
    settings = get_settings()
    parsed = urlsplit(settings.database_url.replace("postgresql+psycopg://", "postgresql://"))
    target_db = parsed.path.lstrip("/")

    admin_url = f"postgresql://{parsed.username}:{parsed.password}@{parsed.hostname}:{parsed.port}/postgres"

    conn = psycopg.connect(admin_url, autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (target_db,))
            exists = cur.fetchone() is not None
            if exists:
                print(f"Database '{target_db}' already exists.")
            else:
                cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(target_db)))
                print(f"Database '{target_db}' created.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
