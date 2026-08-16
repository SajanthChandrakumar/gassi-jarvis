"""Controlled Phase-7 routing from a validated request to deterministic research.

This module deliberately contains no LLM client.  An LLM may choose one of the
small public requests, but asset resolution, plan selection, data access, and
financial calculations remain deterministic application code.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from enum import StrEnum
import math
import re
from typing import Any, Iterable

from .canonical import AssetIdentity, AssetResearchData, CanonicalAssetType, ResearchProvenance
from .findings import ResearchAnalysis
from .historical import EventStudyResult
from .historical_service import HistoricalResearchService
from .relevance import ResearchRelevanceEngine
from .report_service import AssetResearchReportService
from .reports import AssetResearchReport, ReportDepth, ReportMetric
from .serialization import to_jsonable
from .statistical_service import StatisticalResearchService
from .statistics import BetaResult, CorrelationMethod, CorrelationResult, ResultStatus


class ResearchIntent(StrEnum):
    ASSET_ANALYSIS = "asset_analysis"
    ASSET_COMPARISON = "asset_comparison"
    HISTORICAL_ANALYSIS = "historical_analysis"
    STATISTICAL_RELATIONSHIP = "statistical_relationship"
    RISK_ANALYSIS = "risk_analysis"
    VALUATION_ANALYSIS = "valuation_analysis"
    FACTOR_EXPLANATION = "factor_explanation"


class ResearchAnalysisType(StrEnum):
    REPORT = "report"
    CORRELATION = "correlation"
    BETA = "beta"
    VOLATILITY_EVENTS = "volatility_events"
    EVENT_STUDY = "event_study"


class RequestStatus(StrEnum):
    SUCCESS = "success"
    PARTIAL = "partial"
    AMBIGUOUS = "ambiguous"
    INVALID = "invalid"
    FAILED = "failed"


class ResolutionStatus(StrEnum):
    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ResearchRequest:
    """Canonical, bounded request supplied by an LLM or deterministic parser."""

    intent: ResearchIntent
    assets: tuple[str, ...]
    benchmark: str | None = None
    timeframe: str | None = None
    analyses: tuple[ResearchAnalysisType, ...] = ()
    report_depth: ReportDepth = ReportDepth.STANDARD
    parameters: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        assets = tuple(dict.fromkeys(item.strip() for item in self.assets if item and item.strip()))
        if not assets:
            raise ValueError("research request needs at least one asset")
        if not isinstance(self.intent, ResearchIntent):
            raise TypeError("intent must be a ResearchIntent")
        if self.intent is ResearchIntent.ASSET_COMPARISON and len(assets) != 2:
            raise ValueError("asset comparison requires exactly two assets")
        if self.intent is ResearchIntent.STATISTICAL_RELATIONSHIP and len(assets) + (1 if self.benchmark else 0) < 2:
            raise ValueError("statistical relationship requires two assets or an explicit benchmark")
        object.__setattr__(self, "assets", assets)
        object.__setattr__(self, "benchmark", self.benchmark.strip() if self.benchmark else None)
        object.__setattr__(self, "timeframe", self.timeframe.strip().lower() if self.timeframe else None)
        object.__setattr__(self, "analyses", tuple(dict.fromkeys(self.analyses)))
        object.__setattr__(self, "parameters", tuple(sorted((str(key), str(value)) for key, value in self.parameters)))

    @property
    def parameter_map(self) -> dict[str, str]:
        return dict(self.parameters)


@dataclass(frozen=True, slots=True)
class AssetResolution:
    mention: str
    status: ResolutionStatus
    asset: AssetIdentity | None = None
    alternatives: tuple[AssetIdentity, ...] = ()
    message: str | None = None
    assumed_default: bool = False


@dataclass(frozen=True, slots=True)
class ResearchPlan:
    intent: ResearchIntent
    sections: tuple[str, ...]
    steps: tuple[str, ...]
    timeframe_start: date | None
    timeframe_end: date | None


@dataclass(frozen=True, slots=True)
class ExecutionTrace:
    step: str
    status: RequestStatus
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class ComparisonDimension:
    category: str
    left: tuple[ReportMetric, ...]
    right: tuple[ReportMetric, ...]
    compatible: bool
    warning: str | None = None


@dataclass(frozen=True, slots=True)
class AssetComparison:
    left: AssetResearchReport
    right: AssetResearchReport
    dimensions: tuple[ComparisonDimension, ...]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ResearchResponse:
    request: ResearchRequest
    status: RequestStatus
    assets: tuple[AssetResolution, ...]
    plan: ResearchPlan | None
    reports: tuple[AssetResearchReport, ...] = ()
    comparison: AssetComparison | None = None
    historical_results: tuple[EventStudyResult, ...] = ()
    statistical_results: tuple[CorrelationResult | BetaResult, ...] = ()
    warnings: tuple[str, ...] = ()
    sources: tuple[ResearchProvenance, ...] = ()
    trace: tuple[ExecutionTrace, ...] = ()
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        object.__setattr__(self, "assets", tuple(self.assets))
        object.__setattr__(self, "reports", tuple(self.reports))
        object.__setattr__(self, "historical_results", tuple(self.historical_results))
        object.__setattr__(self, "statistical_results", tuple(self.statistical_results))
        object.__setattr__(self, "warnings", tuple(sorted(set(self.warnings))))
        object.__setattr__(self, "sources", tuple(sorted(set(self.sources), key=lambda item: (item.provider or "", item.source_category, item.retrieved_at))))
        object.__setattr__(self, "trace", tuple(self.trace))
        if self.generated_at.tzinfo is None:
            raise ValueError("generated_at must be timezone-aware")
        object.__setattr__(self, "generated_at", self.generated_at.astimezone(timezone.utc))


class AssetResolver:
    """Single source of documented common-name and benchmark defaults."""

    _DEFAULTS: dict[str, tuple[str, CanonicalAssetType, bool]] = {
        "apple": ("AAPL", CanonicalAssetType.EQUITY, False),
        "nvidia": ("NVDA", CanonicalAssetType.EQUITY, False),
        "amd": ("AMD", CanonicalAssetType.EQUITY, False),
        "tesla": ("TSLA", CanonicalAssetType.EQUITY, False),
        "bitcoin": ("BTC", CanonicalAssetType.CRYPTO, False),
        "btc": ("BTC", CanonicalAssetType.CRYPTO, False),
        "ethereum": ("ETH", CanonicalAssetType.CRYPTO, False),
        "eth": ("ETH", CanonicalAssetType.CRYPTO, False),
        # This benchmark default is explicit in the response trace, never silent.
        "nasdaq": ("QQQ", CanonicalAssetType.ETF, True),
        "nasdaq 100": ("QQQ", CanonicalAssetType.ETF, True),
    }

    def resolve(self, mention: str) -> AssetResolution:
        normalized = " ".join(mention.strip().lower().split())
        if not normalized:
            return AssetResolution(mention, ResolutionStatus.UNKNOWN, message="No asset identifier was provided.")
        mapped = self._DEFAULTS.get(normalized)
        if mapped:
            symbol, asset_type, assumed = mapped
            message = "'Nasdaq' was resolved to the documented QQQ ETF benchmark default." if assumed else None
            return AssetResolution(mention, ResolutionStatus.RESOLVED, AssetIdentity(symbol, asset_type), message=message, assumed_default=assumed)
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9.\-]{0,14}", mention.strip()):
            symbol = mention.strip().upper().replace("-USD", "")
            asset_type = CanonicalAssetType.CRYPTO if symbol in {"BTC", "ETH", "SOL", "XRP", "DOGE"} else CanonicalAssetType.EQUITY
            return AssetResolution(mention, ResolutionStatus.RESOLVED, AssetIdentity(symbol, asset_type))
        return AssetResolution(mention, ResolutionStatus.AMBIGUOUS, message="Asset mention is ambiguous; provide a ticker or a supported common name.")


def resolve_timeframe(value: str | None, *, today: date | None = None) -> tuple[date | None, date | None]:
    """Normalize the small supported timeframe vocabulary once, before fetching."""
    if not value or value in {"historisch", "historical", "all"}:
        return None, None
    today = today or datetime.now(timezone.utc).date()
    text = value.strip().lower()
    if text in {"heute", "today", "aktuell", "current"}:
        return today, today
    if text in {"letzte woche", "last week", "1w"}:
        return today - timedelta(days=7), today
    match = re.fullmatch(r"(\d+)\s*([dwmqy])", text)
    if match:
        count, unit = int(match.group(1)), match.group(2)
        days = count * {"d": 1, "w": 7, "m": 30, "q": 91, "y": 365}[unit]
        return today - timedelta(days=days), today
    match = re.fullmatch(r"seit\s+(\d{4})", text)
    if match:
        return date(int(match.group(1)), 1, 1), today
    return None, None


class ResearchPlanner:
    """Approved request-to-service plans. No plan can be supplied by an LLM."""

    _SECTIONS = {
        ResearchIntent.ASSET_ANALYSIS: ("prices", "profile", "fundamentals", "valuation", "earnings", "estimates"),
        ResearchIntent.ASSET_COMPARISON: ("prices", "profile", "fundamentals", "valuation", "earnings", "estimates"),
        ResearchIntent.HISTORICAL_ANALYSIS: ("prices",),
        ResearchIntent.STATISTICAL_RELATIONSHIP: ("prices",),
        ResearchIntent.RISK_ANALYSIS: ("prices", "fundamentals"),
        ResearchIntent.VALUATION_ANALYSIS: ("profile", "valuation"),
        ResearchIntent.FACTOR_EXPLANATION: ("prices", "profile", "fundamentals", "valuation", "earnings"),
    }

    _STEPS = {
        ResearchIntent.ASSET_ANALYSIS: ("canonical_data", "relevance", "asset_report"),
        ResearchIntent.ASSET_COMPARISON: ("canonical_data", "relevance", "asset_reports", "comparison"),
        ResearchIntent.HISTORICAL_ANALYSIS: ("canonical_prices", "volatility_events", "event_study"),
        ResearchIntent.STATISTICAL_RELATIONSHIP: ("canonical_prices", "statistical_analysis"),
        ResearchIntent.RISK_ANALYSIS: ("canonical_data", "relevance", "asset_report"),
        ResearchIntent.VALUATION_ANALYSIS: ("canonical_data", "relevance", "asset_report"),
        ResearchIntent.FACTOR_EXPLANATION: ("canonical_data", "relevance", "asset_report"),
    }

    def plan(self, request: ResearchRequest) -> ResearchPlan:
        start, end = resolve_timeframe(request.timeframe)
        return ResearchPlan(request.intent, self._SECTIONS[request.intent], self._STEPS[request.intent], start, end)


class ResearchResponseValidator:
    """Fail closed on malformed output while retaining visible partial results."""

    def validate(self, response: ResearchResponse) -> ResearchResponse:
        self._finite(response)
        self._finite(to_jsonable(response))
        if response.status is RequestStatus.SUCCESS and not (response.reports or response.historical_results or response.statistical_results):
            raise ValueError("successful research response has no authoritative result")
        for result in response.statistical_results:
            if result.status is ResultStatus.COMPLETE and result.context.observations <= 0:
                raise ValueError("complete statistical result has no observations")
        return response

    def _finite(self, value: Any) -> None:
        if isinstance(value, Decimal) and not value.is_finite():
            raise ValueError("response contains a non-finite decimal")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("response contains a non-finite float")
        if is_dataclass(value):
            for item in fields(value):
                self._finite(getattr(value, item.name))
        elif isinstance(value, dict):
            for item in value.values():
                self._finite(item)
        elif isinstance(value, list):
            for item in value:
                self._finite(item)


class ResearchOrchestrator:
    """Bounded executor that composes Phases 1–6; it never calls Gemini."""

    def __init__(
        self,
        canonical_service: Any,
        *,
        resolver: AssetResolver | None = None,
        planner: ResearchPlanner | None = None,
        relevance: ResearchRelevanceEngine | None = None,
        reports: AssetResearchReportService | None = None,
        historical: HistoricalResearchService | None = None,
        statistics: StatisticalResearchService | None = None,
        validator: ResearchResponseValidator | None = None,
    ) -> None:
        self.canonical_service = canonical_service
        self.resolver = resolver or AssetResolver()
        self.planner = planner or ResearchPlanner()
        self.relevance = relevance or ResearchRelevanceEngine()
        self.reports = reports or AssetResearchReportService()
        self.historical = historical or HistoricalResearchService()
        self.statistics = statistics or StatisticalResearchService()
        self.validator = validator or ResearchResponseValidator()

    def execute(self, request: ResearchRequest) -> ResearchResponse:
        resolutions = tuple(self.resolver.resolve(item) for item in request.assets + ((request.benchmark,) if request.benchmark else ()))
        if any(item.status is not ResolutionStatus.RESOLVED for item in resolutions):
            return self.validator.validate(ResearchResponse(request, RequestStatus.AMBIGUOUS, resolutions, None, warnings=tuple(item.message for item in resolutions if item.message), trace=(ExecutionTrace("asset_resolution", RequestStatus.AMBIGUOUS, "Research was not fetched for unresolved assets."),)))
        plan = self.planner.plan(request)
        warnings = [item.message for item in resolutions if item.message]
        traces: list[ExecutionTrace] = [ExecutionTrace("asset_resolution", RequestStatus.SUCCESS)]
        try:
            data = tuple(self._fetch(item.asset, plan) for item in resolutions if item.asset)
            traces.append(ExecutionTrace("canonical_data", RequestStatus.SUCCESS))
        except Exception as exc:
            return self.validator.validate(ResearchResponse(request, RequestStatus.FAILED, resolutions, plan, warnings=tuple(warnings + [f"Canonical research data could not be retrieved: {exc}"]), trace=tuple(traces + [ExecutionTrace("canonical_data", RequestStatus.FAILED, type(exc).__name__)])))

        try:
            if request.intent is ResearchIntent.HISTORICAL_ANALYSIS:
                result = self._historical(data[0], request)
                response = ResearchResponse(request, self._status_for((result,)), resolutions, plan, historical_results=(result,), warnings=tuple(warnings + list(result.warnings)), sources=self._sources(data), trace=tuple(traces + [ExecutionTrace("historical_research", self._status_for((result,)))]))
            elif request.intent is ResearchIntent.STATISTICAL_RELATIONSHIP:
                result = self._statistical(data[0], data[1], request)
                response = ResearchResponse(request, self._status_for((result,)), resolutions, plan, statistical_results=(result,), warnings=tuple(warnings + list(result.warnings)), sources=self._sources(data), trace=tuple(traces + [ExecutionTrace("statistical_research", self._status_for((result,)))]))
            else:
                reports = tuple(self._report(item, request.report_depth) for item in data)
                comparison = self._comparison(reports[0], reports[1]) if request.intent is ResearchIntent.ASSET_COMPARISON else None
                report_warnings = [warning for report in reports for warning in report.warnings]
                response = ResearchResponse(request, RequestStatus.PARTIAL if any(report.data_quality.status.value != "complete" for report in reports) else RequestStatus.SUCCESS, resolutions, plan, reports=reports, comparison=comparison, warnings=tuple(warnings + report_warnings + (list(comparison.warnings) if comparison else [])), sources=self._sources(data), trace=tuple(traces + [ExecutionTrace("relevance_and_report", RequestStatus.SUCCESS)]))
            return self.validator.validate(response)
        except Exception as exc:
            return self.validator.validate(ResearchResponse(request, RequestStatus.PARTIAL, resolutions, plan, warnings=tuple(warnings + [f"Research execution partially failed: {exc}"]), sources=self._sources(data), trace=tuple(traces + [ExecutionTrace("research_execution", RequestStatus.PARTIAL, type(exc).__name__)])))

    def _fetch(self, asset: AssetIdentity, plan: ResearchPlan) -> AssetResearchData:
        provider_type = "crypto" if asset.asset_type is CanonicalAssetType.CRYPTO else "equity"
        return self.canonical_service.get_asset_research_data(asset.symbol, asset_type=provider_type, sections=plan.sections, start_date=plan.timeframe_start, end_date=plan.timeframe_end)

    def _report(self, data: AssetResearchData, depth: ReportDepth) -> AssetResearchReport:
        return self.reports.build_asset_report(research_data=data, analysis=self.relevance.analyze(data), depth=depth)

    def _historical(self, data: AssetResearchData, request: ResearchRequest) -> EventStudyResult:
        if data.prices is None:
            raise ValueError("historical research requires available canonical prices")
        parameters = request.parameter_map
        lookback = int(parameters.get("lookback", "20"))
        percentile = Decimal(parameters.get("volatility_percentile", "0.90"))
        horizons = tuple(int(item) for item in parameters.get("horizons", "1,5,20").split(","))
        events = self.historical.volatility_percentile_events(data.prices, lookback=lookback, percentile=percentile)
        return self.historical.event_study(data.prices, events, horizons=horizons, event_definition=(("kind", "volatility_percentile"), ("lookback", str(lookback)), ("percentile", str(percentile))))

    def _statistical(self, left: AssetResearchData, right: AssetResearchData, request: ResearchRequest) -> CorrelationResult | BetaResult:
        if left.prices is None or right.prices is None:
            raise ValueError("statistical research requires available canonical prices for both assets")
        analysis = request.analyses[0] if request.analyses else ResearchAnalysisType.CORRELATION
        if analysis is ResearchAnalysisType.BETA:
            return self.statistics.beta(left.prices, right.prices)
        method = CorrelationMethod(request.parameter_map.get("method", CorrelationMethod.PEARSON.value))
        return self.statistics.correlation(left.prices, right.prices, method=method)

    @staticmethod
    def _sources(data: Iterable[AssetResearchData]) -> tuple[ResearchProvenance, ...]:
        sources = []
        for item in data:
            for section in (item.prices, item.profile, item.fundamentals, item.valuation, item.earnings, item.crypto):
                if section is not None:
                    sources.append(section.provenance)
        return tuple(sources)

    @staticmethod
    def _status_for(results: Iterable[Any]) -> RequestStatus:
        statuses = [getattr(item, "status", None) for item in results]
        return RequestStatus.SUCCESS if all(getattr(status, "value", status) == "complete" for status in statuses) else RequestStatus.PARTIAL

    @staticmethod
    def _comparison(left: AssetResearchReport, right: AssetResearchReport) -> AssetComparison:
        dimensions: list[ComparisonDimension] = []
        for category in ("growth", "profitability", "valuation", "earnings", "market_behavior", "risk"):
            left_metrics = tuple(metric for section in left.sections if section.key == category for metric in section.metrics)
            right_metrics = tuple(metric for section in right.sections if section.key == category for metric in section.metrics)
            compatible = bool(left_metrics and right_metrics and {item.key for item in left_metrics} == {item.key for item in right_metrics})
            warning = None if compatible or (not left_metrics and not right_metrics) else "Metrics are unavailable or not definition-compatible for comparison."
            dimensions.append(ComparisonDimension(category, left_metrics, right_metrics, compatible, warning))
        warnings = tuple(item.warning for item in dimensions if item.warning)
        return AssetComparison(left, right, tuple(dimensions), warnings)


def parse_research_question(question: str) -> ResearchRequest:
    """Conservative deterministic fallback parser for the four public Jarvis tools.

    Production Gemini may emit the same schema, but this parser is deliberately
    limited and never turns arbitrary user text into code or provider calls.
    """
    text = question.lower()
    mentions = re.findall(r"\b(?:aapl|amd|nvda(?:s)?|tsla(?:s)?|btc(?:-usd)?|eth(?:-usd)?|qqq|apple|nvidia|tesla|bitcoin|ethereum|nasdaq)\b", text, flags=re.IGNORECASE)
    assets = tuple(dict.fromkeys("NVDA" if item.lower() == "nvdas" else "TSLA" if item.lower() == "tslas" else item for item in mentions))
    if any(word in text for word in ("vergleich", "compare")):
        return ResearchRequest(ResearchIntent.ASSET_COMPARISON, assets[:2], timeframe=_timeframe_from_text(text))
    if any(word in text for word in ("korrel", "correl", "beta")):
        analysis = ResearchAnalysisType.BETA if "beta" in text else ResearchAnalysisType.CORRELATION
        return ResearchRequest(ResearchIntent.STATISTICAL_RELATIONSHIP, assets[:2], timeframe=_timeframe_from_text(text), analyses=(analysis,))
    if any(word in text for word in ("histor", "volatilit")):
        return ResearchRequest(ResearchIntent.HISTORICAL_ANALYSIS, assets[:1], timeframe=_timeframe_from_text(text), analyses=(ResearchAnalysisType.EVENT_STUDY,))
    if any(word in text for word in ("teuer", "valuation", "bewertung")):
        return ResearchRequest(ResearchIntent.VALUATION_ANALYSIS, assets[:1], timeframe=_timeframe_from_text(text))
    if any(word in text for word in ("riskant", "risiko", "risk")):
        return ResearchRequest(ResearchIntent.RISK_ANALYSIS, assets[:1], timeframe=_timeframe_from_text(text))
    if any(word in text for word in ("warum", "faktor", "treib")):
        return ResearchRequest(ResearchIntent.FACTOR_EXPLANATION, assets[:1], timeframe=_timeframe_from_text(text))
    return ResearchRequest(ResearchIntent.ASSET_ANALYSIS, assets[:1], timeframe=_timeframe_from_text(text))


def _timeframe_from_text(text: str) -> str | None:
    match = re.search(r"(?:letzten?|last)\s+(\d+)\s*(jahr(?:en)?|years?|monat(?:en)?|months?)", text)
    if match:
        count, unit = match.groups()
        return f"{count}{'y' if unit.startswith(('jahr', 'year')) else 'm'}"
    return "historisch" if "histor" in text else None
