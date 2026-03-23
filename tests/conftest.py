import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

os.environ["APP_DATABASE_URL"] = "sqlite:///./test_audit_system.db"

from audit_system.db.base import Base  # noqa: E402
from audit_system.db.session import SessionLocal, engine as app_engine, get_db  # noqa: E402
from audit_system.main import app  # noqa: E402


TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=app_engine)
DB_FILE = Path("test_audit_system.db")


@pytest.fixture(autouse=True)
def setup_database() -> None:
    app_engine.dispose()
    if DB_FILE.exists():
        DB_FILE.unlink()
    Base.metadata.create_all(bind=app_engine)
    yield
    app_engine.dispose()
    if DB_FILE.exists():
        DB_FILE.unlink()


@pytest.fixture
def client() -> TestClient:
    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        app_engine.dispose()
        if DB_FILE.exists():
            DB_FILE.unlink()
        Base.metadata.create_all(bind=app_engine)
        yield test_client
    app.dependency_overrides.clear()
