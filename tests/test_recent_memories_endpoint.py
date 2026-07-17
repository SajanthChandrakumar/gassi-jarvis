"""
Tests for GET /api/memories/recent (app/main.py).

This endpoint exists for external dashboards (e.g. Homepage's Custom API
widget) to poll recently saved facts without triggering a Gemini call — it
must stay token-gated like /api/chat and return a stable JSON shape even
when the memory store is empty.

Run from the project root:
    python -m pytest tests/ -v
"""

import os
import tempfile

os.environ["JARVIS_BRAIN_DIR"] = tempfile.mkdtemp(prefix="jarvis_endpoint_brain_")
os.environ["JARVIS_SESSIONS_FILE"] = os.path.join(
    tempfile.mkdtemp(prefix="jarvis_endpoint_sess_"), "sessions.json"
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import app.main as main_module  # noqa: E402
from app.memory import collection  # noqa: E402

TEST_TOKEN = "test-token-recent-memories"
client = TestClient(main_module.app)
AUTH = {"Authorization": f"Bearer {TEST_TOKEN}"}


@pytest.fixture(autouse=True)
def token_and_clean_collection():
    # main.API_TOKEN is a module-level constant read once at import time, so
    # setting JARVIS_API_TOKEN in os.environ has no effect if another test
    # file imported app.main first. Patch the module attribute directly and
    # restore it so we don't leak state into tests that run after this file.
    original_token = main_module.API_TOKEN
    main_module.API_TOKEN = TEST_TOKEN

    existing = collection.get()["ids"]
    if existing:
        collection.delete(ids=existing)

    yield

    main_module.API_TOKEN = original_token
    existing = collection.get()["ids"]
    if existing:
        collection.delete(ids=existing)


class TestRecentMemoriesEndpoint:
    def test_requires_token(self):
        r = client.get("/api/memories/recent")
        assert r.status_code == 401

    def test_rejects_wrong_token(self):
        r = client.get(
            "/api/memories/recent", headers={"Authorization": "Bearer wrong"}
        )
        assert r.status_code == 401

    def test_empty_store_returns_empty_list(self):
        r = client.get("/api/memories/recent", headers=AUTH)
        assert r.status_code == 200
        assert r.json() == {"memories": []}

    def test_returns_saved_facts(self):
        collection.add(
            documents=["Test-Fakt"],
            metadatas=[{"timestamp": "2026-01-01T10:00:00"}],
            ids=["mem_endpoint_test"],
        )
        r = client.get("/api/memories/recent", headers=AUTH)
        assert r.status_code == 200
        body = r.json()
        assert len(body["memories"]) == 1
        assert body["memories"][0]["text"] == "Test-Fakt"
