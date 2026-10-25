from app.trading.research.jarvis_tools import render_research_response
from app.trading.research.orchestration import (
    RequestStatus,
    ResearchIntent,
    ResearchRequest,
    ResearchResponse,
)


def test_default_terminal_does_not_auto_select_keyed_market_data(monkeypatch):
    from app.trading.research.jarvis_tools import create_default_orchestrator
    monkeypatch.setenv("FMP_API_KEY", "configured-but-not-opted-in")
    settings = create_default_orchestrator().canonical_service._client._provider_settings
    for name in ("price", "quote", "profile", "statements", "metrics", "news", "estimates", "etf_info", "crypto"):
        assert "fmp" not in getattr(settings, name)
    assert settings.earnings == ()


def test_response_wording_does_not_render_raw_provider_plan_errors():
    response = ResearchResponse(
        request=ResearchRequest(ResearchIntent.ASSET_ANALYSIS, ("NVDA",)),
        status=RequestStatus.FAILED,
        assets=(),
        plan=None,
        warnings=(
            "402 Premium Query Parameter: upgrade at https://financialmodelingprep.com/plan",
        ),
    )

    text = render_research_response(response)

    assert "402" not in text
    assert "https://" not in text
    assert "Provider data is unavailable for part of this report." in text
