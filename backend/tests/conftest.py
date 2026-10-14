from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DISABLE_SCHEDULER", "1")
    for k in ("ACCESS_PASSWORD", "TMDB_API_KEY", "JELLYFIN_URL", "JELLYFIN_API_KEY", "JELLYSEERR_URL",
              "JELLYSEERR_API_KEY", "LLM_BASE_URL", "LLM_MODEL", "LETTERBOXD_USERNAME", "STATIC_DIR"):
        monkeypatch.delenv(k, raising=False)
    from app import config, settings_store
    from app.engine import taste

    config.reset_env()
    settings_store.invalidate()
    taste.invalidate()
    yield monkeypatch
    config.reset_env()


@pytest.fixture()
def client(env):
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c


@pytest.fixture()
def demo_client(client):
    assert client.post("/api/demo/load").json()["history"] > 20
    return client


@pytest.fixture()
def db(client):
    from app import db as database

    s = database.SessionLocal()
    try:
        yield s
    finally:
        s.close()
