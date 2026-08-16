"""Narrow, read-only Jarvis interface for controlled Phase-7 research plans."""

from __future__ import annotations

from .openbb_client import OpenBBResearchClient
from .orchestration import (
    ResearchAnalysisType,
    ResearchIntent,
    ResearchOrchestrator,
    ResearchRequest,
    ResearchResponse,
)
from .service import CanonicalResearchService
from .serialization import to_jsonable
from .statistics import BetaResult


def create_default_orchestrator() -> ResearchOrchestrator:
    """Construct only read-only provider access; OpenBB remains lazy until a request."""
    return ResearchOrchestrator(CanonicalResearchService(OpenBBResearchClient()))


class JarvisResearchTools:
    """Adapter for exactly four public finance tools, not low-level primitives."""

    def __init__(self, orchestrator: ResearchOrchestrator | None = None) -> None:
        self.orchestrator = orchestrator or create_default_orchestrator()

    def research_asset(self, *, asset: str, timeframe: str | None = None, report_depth: str = "standard") -> ResearchResponse:
        from .reports import ReportDepth
        return self.orchestrator.execute(ResearchRequest(ResearchIntent.ASSET_ANALYSIS, (asset,), timeframe=timeframe, report_depth=ReportDepth(report_depth)))

    def compare_assets(self, *, left_asset: str, right_asset: str, timeframe: str | None = None, report_depth: str = "standard") -> ResearchResponse:
        from .reports import ReportDepth
        return self.orchestrator.execute(ResearchRequest(ResearchIntent.ASSET_COMPARISON, (left_asset, right_asset), timeframe=timeframe, report_depth=ReportDepth(report_depth)))

    def research_history(self, *, asset: str, timeframe: str | None = "historisch", lookback: int = 20, volatility_percentile: str = "0.90") -> ResearchResponse:
        return self.orchestrator.execute(ResearchRequest(ResearchIntent.HISTORICAL_ANALYSIS, (asset,), timeframe=timeframe, analyses=(ResearchAnalysisType.EVENT_STUDY,), parameters=(("lookback", str(lookback)), ("volatility_percentile", volatility_percentile))))

    def analyze_relationship(self, *, asset: str, benchmark: str, timeframe: str | None = None, analysis: str = "correlation") -> ResearchResponse:
        analysis_type = ResearchAnalysisType(analysis)
        if analysis_type not in {ResearchAnalysisType.CORRELATION, ResearchAnalysisType.BETA}:
            raise ValueError("relationship analysis must be correlation or beta")
        return self.orchestrator.execute(ResearchRequest(ResearchIntent.STATISTICAL_RELATIONSHIP, (asset,), benchmark=benchmark, timeframe=timeframe, analyses=(analysis_type,)))

    def dispatch(self, name: str, arguments: dict) -> ResearchResponse:
        method = getattr(self, name, None)
        if name not in {"research_asset", "compare_assets", "research_history", "analyze_relationship"} or not callable(method):
            raise ValueError("unknown read-only finance tool")
        return method(**arguments)


def render_research_response(response: ResearchResponse) -> str:
    """Safe deterministic fallback wording; the structured response is authoritative."""
    if response.status.value in {"ambiguous", "invalid", "failed"}:
        return "Finanzrecherche nicht ausgeführt: " + "; ".join(response.warnings)
    if response.statistical_results:
        result = response.statistical_results[0]
        name = "Beta" if isinstance(result, BetaResult) else "Korrelation"
        value = getattr(result, "beta", None) if name == "Beta" else getattr(result, "coefficient", None)
        return f"{name}: {value if value is not None else 'nicht verfügbar'}; n={result.context.observations}. " + " ".join(result.warnings)
    if response.historical_results:
        result = response.historical_results[0]
        return f"Historische Ereignisstudie: {len(result.events)} Ereignisse, Status {result.status.value}. " + " ".join(result.warnings)
    if response.comparison:
        return f"Vergleich {response.comparison.left.asset.symbol} / {response.comparison.right.asset.symbol} erstellt. " + " ".join(response.warnings)
    if response.reports:
        report = response.reports[0]
        return f"Research-Report für {report.asset.symbol} erstellt ({report.data_quality.status.value}). " + " ".join(response.warnings)
    return "Die Finanzrecherche lieferte kein verwertbares Ergebnis."


def response_payload(response: ResearchResponse) -> dict:
    """JSON-safe output for the agent boundary; no provider text becomes instructions."""
    return to_jsonable(response)
