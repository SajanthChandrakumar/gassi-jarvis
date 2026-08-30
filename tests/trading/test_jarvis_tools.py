from app.trading.research.jarvis_tools import render_research_response
from app.trading.research.orchestration import (
    RequestStatus,
    ResearchIntent,
    ResearchRequest,
    ResearchResponse,
)


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
