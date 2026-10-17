import os
import tempfile

import pytest

os.environ.setdefault("JARVIS_BRAIN_DIR", tempfile.mkdtemp(prefix="jarvis_run_brain_"))
os.environ.setdefault("JARVIS_SESSIONS_FILE", os.path.join(tempfile.mkdtemp(prefix="jarvis_run_sess_"), "sessions.json"))

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main_module  # noqa: E402
from app.trading.research.orchestration import (
    ResearchIntent,
    ResearchRequest,
    ResearchResponse,
    RequestStatus,
)  # noqa: E402


class FakeResearchTools:
    def __init__(self):
        self.calls = []

    def dispatch(self, name, arguments):
        self.calls.append((name, arguments))
        intent = {
            "research_asset": ResearchIntent.ASSET_ANALYSIS,
            "compare_assets": ResearchIntent.ASSET_COMPARISON,
            "research_history": ResearchIntent.HISTORICAL_ANALYSIS,
            "analyze_relationship": ResearchIntent.STATISTICAL_RELATIONSHIP,
        }[name]
        assets = (
            (arguments["left_asset"], arguments["right_asset"])
            if name == "compare_assets"
            else (arguments["asset"],)
        )
        request = ResearchRequest(
            intent,
            assets,
            benchmark=arguments.get("benchmark"),
            timeframe=arguments.get("timeframe"),
        )
        return ResearchResponse(request, RequestStatus.SUCCESS, (), None)


def test_research_run_endpoint_dispatches_validated_read_only_workflow(monkeypatch):
    token = "research-run-token"
    fake = FakeResearchTools()
    monkeypatch.setattr(main_module, "API_TOKEN", token)
    monkeypatch.setattr(main_module, "research_tools", fake)
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


@pytest.mark.parametrize(
    ("requested_timeframe", "expected_timeframe"),
    [
        ("1m", "1m"),
        ("3m", "3m"),
        ("6m", "6m"),
        ("1y", "1y"),
        ("2y", "2y"),
        ("5y", "5y"),
        ("all", "all"),
        (None, "1y"),
    ],
)
def test_research_run_accepts_timeframes_without_gemini(
    monkeypatch,
    requested_timeframe,
    expected_timeframe,
):
    token = "research-run-token"
    fake = FakeResearchTools()
    monkeypatch.setattr(main_module, "API_TOKEN", token)
    monkeypatch.setattr(main_module, "research_tools", fake)

    def gemini_unavailable(*args, **kwargs):
        raise RuntimeError("Gemini is unavailable")

    monkeypatch.setattr(main_module, "get_gemini_response", gemini_unavailable)
    client = TestClient(main_module.app)
    payload = {"mode": "asset", "asset": "NVDA"}
    if requested_timeframe is not None:
        payload["timeframe"] = requested_timeframe

    response = client.post(
        "/api/research/run",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
    )

    assert response.status_code == 200
    assert fake.calls == [
        ("research_asset", {"asset": "NVDA", "timeframe": expected_timeframe})
    ]


def test_research_run_rejects_missing_benchmark_for_comparison(monkeypatch):
    monkeypatch.setattr(main_module, "API_TOKEN", "research-run-token")
    client = TestClient(main_module.app)

    response = client.post(
        "/api/research/run",
        headers={"Authorization": "Bearer research-run-token"},
        json={"mode": "compare", "asset": "NVDA", "timeframe": "1y"},
    )

    assert response.status_code == 422
