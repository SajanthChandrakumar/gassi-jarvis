import os
import tempfile
from types import SimpleNamespace

os.environ.setdefault("JARVIS_BRAIN_DIR", tempfile.mkdtemp(prefix="jarvis_run_brain_"))
os.environ.setdefault("JARVIS_SESSIONS_FILE", os.path.join(tempfile.mkdtemp(prefix="jarvis_run_sess_"), "sessions.json"))

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main_module  # noqa: E402


class FakeResearchTools:
    def __init__(self):
        self.calls = []

    def dispatch(self, name, arguments):
        self.calls.append((name, arguments))
        return SimpleNamespace(status=SimpleNamespace(value="success"))


def test_research_run_endpoint_dispatches_validated_read_only_workflow(monkeypatch):
    token = "research-run-token"
    fake = FakeResearchTools()
    monkeypatch.setattr(main_module, "API_TOKEN", token)
    monkeypatch.setattr(main_module, "research_tools", fake)
    monkeypatch.setattr(main_module, "render_research_response", lambda _: "Structured result")
    monkeypatch.setattr(main_module, "response_payload", lambda _: {"status": "success", "reports": []})
    client = TestClient(main_module.app)

    response = client.post(
        "/api/research/run",
        headers={"Authorization": f"Bearer {token}"},
        json={"mode": "relationship", "asset": "BTC", "benchmark": "QQQ", "timeframe": "2y", "analysis": "correlation"},
    )

    assert response.status_code == 200
    assert fake.calls == [("analyze_relationship", {"asset": "BTC", "benchmark": "QQQ", "timeframe": "2y", "analysis": "correlation"})]
    assert response.json()["action_taken"] == "finance_research:analyze_relationship"
    assert response.json()["research_payload"]["status"] == "success"


def test_research_run_rejects_missing_benchmark_for_comparison(monkeypatch):
    monkeypatch.setattr(main_module, "API_TOKEN", "research-run-token")
    client = TestClient(main_module.app)

    response = client.post(
        "/api/research/run",
        headers={"Authorization": "Bearer research-run-token"},
        json={"mode": "compare", "asset": "NVDA", "timeframe": "1y"},
    )

    assert response.status_code == 422
