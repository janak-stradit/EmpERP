import shutil
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app.models  # noqa: F401  (registers all models on Base.metadata)
from app.api import deps as deps_module
from app.core import files as files_module
from app.core.config import get_settings
from app.db.base import Base
from app.main import app


@pytest.fixture(scope="session", autouse=True)
def isolated_upload_root():
    temp_dir = Path(tempfile.mkdtemp(prefix="emperp_test_uploads_"))
    original_root = files_module.UPLOAD_ROOT
    files_module.UPLOAD_ROOT = temp_dir
    yield temp_dir
    files_module.UPLOAD_ROOT = original_root
    shutil.rmtree(temp_dir, ignore_errors=True)

TEST_DB_NAME = "emp_erp_test"


def _test_database_url(base_url: str) -> str:
    prefix, _, _ = base_url.rpartition("/")
    return f"{prefix}/{TEST_DB_NAME}"


@pytest.fixture(scope="session")
def test_engine():
    settings = get_settings()
    admin_url = settings.database_url.replace("postgresql+psycopg://", "postgresql://")
    parsed = urlsplit(admin_url)
    conn = psycopg.connect(
        f"postgresql://{parsed.username}:{parsed.password}@{parsed.hostname}:{parsed.port}/postgres",
        autocommit=True,
    )
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (TEST_DB_NAME,))
            if cur.fetchone() is None:
                cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(TEST_DB_NAME)))
    finally:
        conn.close()

    engine = create_engine(_test_database_url(settings.database_url))
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture()
def db_session(test_engine):
    testing_session_local = sessionmaker(bind=test_engine, autoflush=False, autocommit=False)
    session = testing_session_local()
    for table in reversed(Base.metadata.sorted_tables):
        session.execute(table.delete())
    session.commit()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(db_session):
    def override_get_db():
        yield db_session

    app.dependency_overrides[deps_module.get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
