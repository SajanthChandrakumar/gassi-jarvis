"""Deterministic composition of canonical research and Phase-3 findings."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Iterable, Sequence

from .canonical import AssetResearchData, Availability, CanonicalAssetType, FreshnessStatus, QualityStatus, ResearchProvenance
from .findings import FindingCategory, FindingDirection, FindingType, ResearchAnalysis, ResearchFinding
from .reports import (
    AssetResearchReport,
    ReportDataConfidence,
    ReportDataCoverage,
    ReportDepth,
    ReportFactor,
    ReportMetric,
    ReportRisk,
    ReportSection,
    ReportSource,
    ReportSummary,
)


@dataclass(frozen=True, slots=True)
class ReportPolicy:
    """Presentation limits only; research scoring remains owned by Phase 3."""

    brief_findings: int = 5
    standard_findings: int = 8
    detailed_findings: int = 12
    max_per_category: int = 2

    def limit_for(self, depth: ReportDepth) -> int:
        return {
            ReportDepth.BRIEF: self.brief_findings,
            ReportDepth.STANDARD: self.standard_findings,
            ReportDepth.DETAILED: self.detailed_findings,
        }[depth]


class AssetResearchReportService:
    """Builds reports from supplied data only; it never fetches or invokes an LLM."""

    def __init__(self, policy: ReportPolicy | None = None) -> None:
        self.policy = policy or ReportPolicy()

    def build_asset_report(
        self,
        *,
        research_data: AssetResearchData,
        analysis: ResearchAnalysis,
        depth: ReportDepth = ReportDepth.STANDARD,
    ) -> AssetResearchReport:
        if research_data.asset != analysis.asset:
            raise ValueError("research_data and analysis must refer to the same canonical asset")
        selected = self._select_key_findings(analysis, self.policy.limit_for(depth))
        factors = self._factors(analysis.findings)
        risks = self._risks(analysis.findings)
        coverage = self._coverage(research_data)
        sources = self._sources(research_data, analysis.findings)
        sections = self._sections(research_data, selected, risks, coverage, sources)
        warnings = self._warnings(research_data, analysis, coverage)
        return AssetResearchReport(
            asset=research_data.asset,
            depth=depth,
            summary=ReportSummary(
                dominant_theme=self._dominant_theme(selected),
                strongest_positive_finding_id=self._first_id(factors[0]),
                strongest_negative_finding_id=self._first_id(factors[1]),
                main_risk_finding_id=risks[0].finding_id if risks else None,
                data_confidence=self._data_confidence(research_data.quality.status),
            ),
            sections=sections,
            key_findings=selected,
            positive_factors=factors[0],
            negative_factors=factors[1],
            mixed_factors=factors[2],
            risks=risks,
            data_quality=research_data.quality,
            data_coverage=coverage,
            sources=sources,
            as_of=self._as_of(research_data, analysis.findings),
            # This is the latest retained input retrieval time, not a wall-clock build time.
            generated_at=max((source.retrieved_at for source in sources), default=None),
            warnings=warnings,
        )

    def _select_key_findings(self, analysis: ResearchAnalysis, limit: int) -> tuple[ResearchFinding, ...]:
        """Use Phase-3 order and the same category-cap diversity rule, without rescoring."""
        selected: list[ResearchFinding] = []
        category_counts: Counter[FindingCategory] = Counter()
        for finding in analysis.findings:
            if category_counts[finding.category] >= self.policy.max_per_category:
                continue
            selected.append(finding)
            category_counts[finding.category] += 1
            if len(selected) == limit:
                break
        return tuple(selected)

    @staticmethod
    def _factor(finding: ResearchFinding) -> ReportFactor:
        return ReportFactor(finding.id, finding.category.value, finding.metric, finding.direction.value, finding.confidence)

    def _factors(self, findings: Sequence[ResearchFinding]) -> tuple[tuple[ReportFactor, ...], tuple[ReportFactor, ...], tuple[ReportFactor, ...]]:
        positive_categories = {FindingCategory.GROWTH, FindingCategory.PROFITABILITY, FindingCategory.CASH_FLOW, FindingCategory.EARNINGS}
        negative: list[ReportFactor] = []
        positive: list[ReportFactor] = []
        mixed: list[ReportFactor] = []
        for finding in findings:
            if finding.direction is FindingDirection.MIXED or finding.conflicts_with:
                mixed.append(self._factor(finding))
            elif finding.category in positive_categories and finding.direction is FindingDirection.UP:
                positive.append(self._factor(finding))
            elif finding.category in positive_categories and finding.direction is FindingDirection.DOWN:
                negative.append(self._factor(finding))
            elif finding.category is FindingCategory.BALANCE_SHEET and finding.metric == "total_debt" and finding.direction is FindingDirection.UP:
                negative.append(self._factor(finding))
        return tuple(positive), tuple(negative), tuple(mixed)

    @staticmethod
    def _risk(finding: ResearchFinding) -> ReportRisk:
        evidence = [("finding_type", finding.finding_type.value), ("direction", finding.direction.value)]
        if finding.evidence.relative_change is not None:
            evidence.append(("relative_change", str(finding.evidence.relative_change)))
        if finding.evidence.percentile is not None:
            evidence.append(("percentile", str(finding.evidence.percentile)))
        return ReportRisk(finding.id, finding.category.value, finding.metric, tuple(evidence), finding.confidence)

    def _risks(self, findings: Sequence[ResearchFinding]) -> tuple[ReportRisk, ...]:
        risks: list[ReportRisk] = []
        risk_categories = {FindingCategory.DATA_QUALITY, FindingCategory.CASH_FLOW, FindingCategory.PROFITABILITY, FindingCategory.GROWTH}
        for finding in findings:
            is_risk = (
                finding.category is FindingCategory.DATA_QUALITY
                or finding.finding_type is FindingType.DIVERGENCE
                or (finding.category in risk_categories and finding.direction is FindingDirection.DOWN)
                or (finding.category is FindingCategory.BALANCE_SHEET and finding.metric == "total_debt" and finding.direction is FindingDirection.UP)
            )
            if is_risk:
                risks.append(self._risk(finding))
        return tuple(risks)

    def _sections(self, data, selected, risks, coverage, sources) -> tuple[ReportSection, ...]:
        finding_sections = self._finding_sections(data, selected)
        common = [self._overview(data, selected)]
        if selected:
            common.append(self._section("key_findings", "Key Findings", selected))
        asset_type = data.asset.asset_type
        if asset_type is CanonicalAssetType.CRYPTO:
            order = ("price_trend", "volume", "market_structure")
        elif asset_type is CanonicalAssetType.ETF:
            order = ("price_trend", "market_behavior", "fund_market_characteristics")
        else:
            order = ("growth", "profitability", "cash_flow", "balance_sheet", "valuation", "earnings", "market_behavior")
        common.extend(finding_sections[key] for key in order if key in finding_sections)
        if risks:
            risk_findings = tuple(item for item in selected if item.id in {risk.finding_id for risk in risks})
            common.append(self._section("risks", "Risks", risk_findings))
        data_warnings = tuple(warning for item in coverage for warning in item.warnings)
        if data_warnings or any(item.availability is not Availability.AVAILABLE for item in coverage):
            common.append(ReportSection("data_quality", "Data Quality", warnings=data_warnings))
        if sources:
            common.append(ReportSection("sources", "Sources", provenance=tuple(ResearchProvenance(source.provider, source.source_category, source.retrieved_at) for source in sources)))
        return tuple(common)

    def _finding_sections(self, data: AssetResearchData, selected: Sequence[ResearchFinding]) -> dict[str, ReportSection]:
        grouped: defaultdict[str, list[ResearchFinding]] = defaultdict(list)
        keys = {
            FindingCategory.GROWTH: ("growth", "Growth"),
            FindingCategory.PROFITABILITY: ("profitability", "Profitability / Margins"),
            FindingCategory.CASH_FLOW: ("cash_flow", "Cash Flow"),
            FindingCategory.BALANCE_SHEET: ("balance_sheet", "Balance Sheet"),
            FindingCategory.EARNINGS: ("earnings", "Earnings / Estimates"),
            FindingCategory.PRICE: ("market_behavior", "Price / Market Behavior"),
            FindingCategory.CRYPTO_MARKET: ("price_trend", "Price / Trend"),
            FindingCategory.VOLUME: ("volume", "Volume"),
            FindingCategory.CROSS_METRIC: ("market_behavior" if data.asset.asset_type is not CanonicalAssetType.CRYPTO else "price_trend", "Price / Market Behavior"),
        }
        for finding in selected:
            if finding.category in keys:
                grouped[keys[finding.category][0]].append(finding)
        sections: dict[str, ReportSection] = {}
        for category, (key, title) in keys.items():
            if grouped[key]:
                sections[key] = self._section(key, title, tuple(grouped[key]))
        if data.valuation is not None and any(value is not None for _, value in data.valuation.metrics):
            sections["valuation"] = ReportSection(
                "valuation", "Valuation",
                metrics=tuple(ReportMetric(key, value) for key, value in data.valuation.metrics if value is not None),
                provenance=(data.valuation.provenance,), warnings=data.valuation.quality.warnings,
            )
        if data.crypto is not None and any(value is not None for value in (data.crypto.market_cap, data.crypto.circulating_supply, data.crypto.total_supply)):
            sections["market_structure"] = ReportSection(
                "market_structure", "Market Structure",
                metrics=tuple(ReportMetric(key, value) for key, value in (("market_cap", data.crypto.market_cap), ("circulating_supply", data.crypto.circulating_supply), ("total_supply", data.crypto.total_supply)) if value is not None),
                provenance=(data.crypto.provenance,), warnings=data.crypto.quality.warnings,
            )
        if data.asset.asset_type is CanonicalAssetType.ETF and data.valuation is not None and "valuation" in sections:
            valuation = sections.pop("valuation")
            sections["fund_market_characteristics"] = ReportSection("fund_market_characteristics", "Fund / Market Characteristics", metrics=valuation.metrics, provenance=valuation.provenance, warnings=valuation.warnings)
        return sections

    @staticmethod
    def _section(key: str, title: str, findings: Sequence[ResearchFinding]) -> ReportSection:
        provenance = tuple(provenance for finding in findings for provenance in finding.provenance)
        warnings = tuple(warning for finding in findings for warning in finding.quality.warnings)
        metrics = tuple(ReportMetric(finding.evidence.metric, finding.evidence.current_value, finding.evidence.previous_value, finding.evidence.comparison_period, finding.id) for finding in findings)
        return ReportSection(key, title, tuple(findings), metrics, warnings, provenance)

    def _overview(self, data: AssetResearchData, selected: Sequence[ResearchFinding]) -> ReportSection:
        metrics: list[ReportMetric] = []
        provenance: list[ResearchProvenance] = []
        if data.prices is not None and data.prices.bars and data.prices.bars[-1].close is not None:
            metrics.append(ReportMetric("last_close", data.prices.bars[-1].close, unit=data.prices.currency))
            provenance.append(data.prices.provenance)
        elif data.crypto is not None and data.crypto.price_history.bars and data.crypto.price_history.bars[-1].close is not None:
            metrics.append(ReportMetric("last_close", data.crypto.price_history.bars[-1].close, unit=data.crypto.price_history.currency))
            provenance.append(data.crypto.provenance)
        return ReportSection("overview", "Overview", tuple(selected[:1]), tuple(metrics), provenance=tuple(provenance))

    def _coverage(self, data: AssetResearchData) -> tuple[ReportDataCoverage, ...]:
        sections = [
            ("prices", data.prices), ("profile", data.profile), ("fundamentals", data.fundamentals),
            ("valuation", data.valuation), ("earnings", data.earnings), ("estimates", data.estimates), ("crypto_market", data.crypto),
        ]
        failures = defaultdict(list)
        for failure in data.failures:
            failures[failure.section.split(".")[0]].append(failure.message)
        coverage: list[ReportDataCoverage] = []
        for name, section in sections:
            if section is None:
                availability = Availability.UPSTREAM_ERROR if name in failures else Availability.NOT_REQUESTED
                coverage.append(ReportDataCoverage(name, availability, FreshnessStatus.UNKNOWN, tuple(failures[name])))
                continue
            availability = getattr(section, "availability", section.quality.availability)
            warnings = list(section.quality.warnings) + failures[name]
            if section.freshness is FreshnessStatus.STALE:
                warnings.append(f"{name} data is stale.")
            elif section.quality.status is QualityStatus.PARTIAL:
                warnings.append(f"{name} data is partial.")
            elif section.quality.status is QualityStatus.EMPTY:
                warnings.append(f"{name} data is empty.")
            coverage.append(ReportDataCoverage(name, availability, section.freshness, tuple(warnings)))
        if data.asset.asset_type is CanonicalAssetType.CRYPTO:
            coverage.append(ReportDataCoverage("derivatives_metadata", Availability.NOT_SUPPORTED, FreshnessStatus.UNKNOWN, ("Phase 2 does not provide derivatives metadata.",)))
        return tuple(coverage)

    @staticmethod
    def _sources(data: AssetResearchData, findings: Iterable[ResearchFinding]) -> tuple[ReportSource, ...]:
        provenance: list[ResearchProvenance] = []
        for section in (data.prices, data.profile, data.fundamentals, data.valuation, data.earnings, data.crypto):
            if section is not None:
                provenance.append(section.provenance)
        provenance.extend(item for finding in findings for item in finding.provenance)
        unique = {(item.provider, item.source_category, item.retrieved_at): item for item in provenance}
        return tuple(ReportSource(provider, category, retrieved_at) for provider, category, retrieved_at in sorted(unique))

    @staticmethod
    def _warnings(data, analysis, coverage) -> tuple[str, ...]:
        warnings = list(data.quality.warnings) + list(analysis.warnings)
        warnings.extend(warning for item in coverage for warning in item.warnings)
        return tuple(sorted(set(warnings)))

    @staticmethod
    def _dominant_theme(findings: Sequence[ResearchFinding]) -> str | None:
        if not findings:
            return None
        counts = Counter(item.theme for item in findings)
        return sorted(counts, key=lambda item: (-counts[item], item))[0]

    @staticmethod
    def _first_id(factors: Sequence[ReportFactor]) -> str | None:
        return factors[0].finding_id if factors else None

    @staticmethod
    def _data_confidence(status: QualityStatus) -> ReportDataConfidence:
        return {
            QualityStatus.COMPLETE: ReportDataConfidence.HIGH,
            QualityStatus.PARTIAL: ReportDataConfidence.MEDIUM,
            QualityStatus.STALE: ReportDataConfidence.MEDIUM,
            QualityStatus.EMPTY: ReportDataConfidence.LOW,
            QualityStatus.ERROR: ReportDataConfidence.LOW,
        }[status]

    @staticmethod
    def _as_of(data: AssetResearchData, findings: Iterable[ResearchFinding]) -> datetime | None:
        values = [getattr(section, "as_of", None) for section in (data.prices, data.profile, data.fundamentals, data.valuation, data.earnings, data.crypto) if section is not None]
        values.extend(finding.as_of for finding in findings)
        return max((item for item in values if item is not None), default=None)
