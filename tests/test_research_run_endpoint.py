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
from app.trading.research.search import AssetSearchError  # noqa: E402


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


def test_research_run_preserves_selected_asset_and_benchmark_identity(monkeypatch):
    token = "research-run-token"
    fake = FakeResearchTools()
    monkeypatch.setattr(main_module, "API_TOKEN", token)
    monkeypatch.setattr(main_module, "research_tools", fake)
    client = TestClient(main_module.app)

    response = client.post(
        "/api/research/run",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "mode": "compare",
            "asset": "VWRL",
            "benchmark": "BTC-USD",
            "asset_type": "etf",
            "exchange": "XLON",
            "currency": "GBP",
            "benchmark_asset_type": "crypto",
            "benchmark_exchange": "CCC",
            "benchmark_currency": "USD",
            "refresh": True,
        },
    )

    assert response.status_code == 200
    assert fake.calls == [
        (
            "compare_assets",
            {
                "left_asset": "VWRL",
                "right_asset": "BTC-USD",
                "timeframe": "1y",
                "asset_type": "etf",
                "exchange": "XLON",
                "currency": "GBP",
                "benchmark_asset_type": "crypto",
                "benchmark_exchange": "CCC",
                "benchmark_currency": "USD",
                "refresh": True,
            },
        )
    ]


def test_research_search_returns_typed_choices_and_requires_authentication(monkeypatch):
    class FakeAssetSearch:
        def __init__(self):
            self.calls = []

        def search(self, query, *, asset_type):
            self.calls.append((query, asset_type))
            return {
                "query": query,
                "results": [{
                    "symbol": "NVDA",
                    "name": "NVIDIA Corporation",
                    "exchange": None,
                    "currency": None,
                    "asset_type": "equity",
                    "isin": None,
                }],
                "provider": "sec",
            }

    token = "research-search-token"
    fake = FakeAssetSearch()
    monkeypatch.setattr(main_module, "API_TOKEN", token)
    monkeypatch.setattr(main_module, "asset_search", fake, raising=False)
    client = TestClient(main_module.app)

    unauthorized = client.get("/api/research/search?query=NVDA&asset_type=equity")
    response = client.get(
        "/api/research/search?query=NVDA&asset_type=equity",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert unauthorized.status_code == 401
    assert response.status_code == 200
    assert response.json() == {
        "query": "NVDA",
        "results": [{
            "symbol": "NVDA",
            "name": "NVIDIA Corporation",
            "exchange": None,
            "currency": None,
            "asset_type": "equity",
            "isin": None,
        }],
        "provider": "sec",
    }
    assert fake.calls == [("NVDA", "equity")]


def test_research_search_rejects_whitespace_without_calling_provider(monkeypatch):
    class FakeAssetSearch:
        def __init__(self):
            self.calls = []

        def search(self, query, *, asset_type):
            self.calls.append((query, asset_type))
            return {"query": query, "results": [], "provider": "yfinance"}

    token = "research-search-token"
    fake = FakeAssetSearch()
    monkeypatch.setattr(main_module, "API_TOKEN", token)
    monkeypatch.setattr(main_module, "asset_search", fake, raising=False)
    client = TestClient(main_module.app)

    response = client.get(
        "/api/research/search?query=%20%20&asset_type=etf",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 422
    assert fake.calls == []


def test_research_search_hides_provider_error_details(monkeypatch):
    class FailedSearch:
        def search(self, query, *, asset_type):
            raise AssetSearchError("Asset search is currently unavailable for the selected category.")

    token = "research-search-token"
    monkeypatch.setattr(main_module, "API_TOKEN", token)
    monkeypatch.setattr(main_module, "asset_search", FailedSearch(), raising=False)
    client = TestClient(main_module.app)

    response = client.get(
        "/api/research/search?query=Bitcoin&asset_type=crypto",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 503
    assert response.json() == {
        "detail": "Asset search is currently unavailable for the selected category."
    }
