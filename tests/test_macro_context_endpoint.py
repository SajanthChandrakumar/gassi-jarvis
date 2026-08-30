import os
import tempfile

os.environ.setdefault("JARVIS_BRAIN_DIR", tempfile.mkdtemp(prefix="jarvis_macro_brain_"))
os.environ.setdefault("JARVIS_SESSIONS_FILE", os.path.join(tempfile.mkdtemp(prefix="jarvis_macro_sess_"), "sessions.json"))

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main_module  # noqa: E402


def test_macro_context_endpoint_is_authenticated_and_returns_canonical_payload(monkeypatch):
    token = "macro-test-token"
    monkeypatch.setattr(main_module, "API_TOKEN", token)
    expected = {"series": [{"asset": {"symbol": "CPI"}, "observations": []}], "failures": []}
    monkeypatch.setattr(main_module, "macro_context_payload", lambda _: expected, raising=False)
    client = TestClient(main_module.app)

    assert client.get("/api/research/macro").status_code == 401
    response = client.get("/api/research/macro", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json() == expected
