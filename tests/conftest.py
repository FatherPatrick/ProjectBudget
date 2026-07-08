"""Shared fixtures: every test runs against a fresh temp database."""
import pytest

from app import db as dbmod


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Point the storage layer at a throwaway DB so tests never touch data/."""
    monkeypatch.setattr(dbmod, "DATA_DIR", tmp_path)
    monkeypatch.setattr(dbmod, "DB_PATH", tmp_path / "test.db")
    dbmod.init_db()


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as c:
        yield c
