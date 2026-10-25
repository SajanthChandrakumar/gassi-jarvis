"""Deterministic composition of canonical research and Phase-3 findings."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from typing import Iterable, Sequence

from .canonical import AssetResearchData, Availability, CanonicalAssetType, DataQuality, FreshnessStatus, QualityStatus, ResearchProvenance
from .findings import FindingCategory, FindingDirection, FindingType, ResearchAnalysis, ResearchFinding
from .reports import (
    AssetResearchReport,
    ReportDataConfidence,
    ReportDataCoverage,
    ReportDepth,
    ReportFactor,
    ReportMetric,
    ReportPricePoint,
    ReportRisk,
    ReportSection,
    ReportSource,
    ReportSummary,
)


_MONETARY_STATEMENT_METRICS = {
    "revenue", "operating_income", "net_income", "total_assets", "total_debt",
    "cash", "equity", "free_cash_flow", "operating_cash_flow",
}


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
        missing_essentials = self._missing_essentials(research_data, coverage)
        data_quality = self._report_quality(research_data.quality, missing_essentials, coverage)
        sources = self._sources(research_data, analysis.findings)
        sections = self._sections(research_data, selected, risks, coverage, sources)
        warnings = self._warnings(research_data, analysis, coverage, missing_essentials)
        price_history, price_history_total = self._price_history(research_data)
        return AssetResearchReport(
            asset=research_data.asset,
            depth=depth,
            summary=ReportSummary(
                dominant_theme=self._dominant_theme(selected),
                strongest_positive_finding_id=self._first_id(factors[0]),
                strongest_negative_finding_id=self._first_id(factors[1]),
                main_risk_finding_id=risks[0].finding_id if risks else None,
                data_confidence=self._data_confidence(data_quality.status),
            ),
            sections=sections,
            key_findings=selected,
            positive_factors=factors[0],
            negative_factors=factors[1],
            mixed_factors=factors[2],
            risks=risks,
            data_quality=data_quality,
            data_coverage=coverage,
            sources=sources,
            as_of=self._as_of(research_data, analysis.findings),
            # This is the latest retained input retrieval time, not a wall-clock build time.
            generated_at=max((source.retrieved_at for source in sources), default=None),
            price_history=price_history,
            price_history_total=price_history_total,
            earnings=research_data.earnings.observations if research_data.earnings is not None else (),
            news=research_data.news.articles if research_data.news is not None else (),
            filings=research_data.filings.items if research_data.filings is not None else (),
            warnings=warnings,
            is_partial=bool(missing_essentials) or data_quality.status is not QualityStatus.COMPLETE,
            missing_essentials=missing_essentials,
            fund_composition=research_data.fund_composition,
            price_as_of=self._price_as_of(research_data),
            fund_profile_secondary=research_data.fund_profile_secondary,
            financial_history=(
                research_data.fundamentals.statements
                if research_data.fundamentals is not None else ()
            ),
        )

    @staticmethod
    def _price_as_of(data: AssetResearchData) -> datetime | None:
        if data.quote is not None and data.quote.last_price is not None:
            return data.quote.as_of
        series = data.prices or (data.crypto.price_history if data.crypto is not None else None)
        return series.bars[-1].timestamp if series is not None and series.bars else None

    @staticmethod
    def _price_history(data: AssetResearchData) -> tuple[tuple[ReportPricePoint, ...], int | None]:
        series = data.prices or (data.crypto.price_history if data.crypto is not None else None)
        if series is None:
            return (), None
        points = tuple(ReportPricePoint(bar.timestamp, bar.close) for bar in series.bars if bar.close is not None)
        total = len(points)
        if total <= 180:
            return points, total
        return tuple(points[index * (total - 1) // 179] for index in range(180)), total

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
        common = [self._snapshot(data, selected)]
        if selected:
            common.append(self._section("key_findings", "Key Findings", selected))
        asset_type = data.asset.asset_type
        if asset_type is CanonicalAssetType.CRYPTO:
            order = ("price_trend", "volume", "market_structure")
        elif asset_type is CanonicalAssetType.ETF:
            order = ("price_trend", "market_behavior", "fund_market_characteristics", "fund_characteristics", "fund_provider_observations")
        else:
            order = ("fundamentals", "growth", "profitability", "cash_flow", "balance_sheet", "valuation", "earnings", "estimates", "market_behavior")
        common.extend(finding_sections[key] for key in order if key in finding_sections)
        if risks:
            risk_findings = tuple(item for item in selected if item.id in {risk.finding_id for risk in risks})
            common.append(self._section("risks", "Risks", risk_findings))
        data_warnings = tuple(warning for item in coverage for warning in item.warnings)
        if data_warnings or any(item.availability is not Availability.AVAILABLE for item in coverage):
            common.append(ReportSection("data_quality", "Data Quality", warnings=data_warnings))
        if sources:
            common.append(ReportSection("sources", "Sources", provenance=tuple(ResearchProvenance(source.provider, source.source_category, source.retrieved_at, attempts=source.attempts) for source in sources)))
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
        if data.fundamentals is not None:
            latest: dict[str, tuple[Decimal, str | None, str | None]] = {}
            for statement in sorted(data.fundamentals.statements, key=lambda item: item.period_end or datetime.min.replace(tzinfo=data.fundamentals.provenance.retrieved_at.tzinfo)):
                for key, value in statement.values:
                    if value is not None:
                        period = (
                            f"{statement.period.value}:{statement.period_end.date().isoformat()}"
                            if statement.period_end is not None and statement.period.value != "other" else None
                        )
                        latest[key] = (value, statement.currency, period)
            if latest:
                sections["fundamentals"] = ReportSection(
                    "fundamentals", "Fundamentals",
                    metrics=tuple(
                        ReportMetric(
                            key, value,
                            unit=(currency or "unknown") if key in _MONETARY_STATEMENT_METRICS else None,
                            period=period,
                        )
                        for key, (value, currency, period) in latest.items()
                    ),
                    provenance=(data.fundamentals.provenance,),
                    warnings=data.fundamentals.quality.warnings,
                )
        if data.valuation is not None and any(value is not None for _, value in data.valuation.metrics):
            sections["valuation"] = ReportSection(
                "valuation", "Valuation",
                metrics=tuple(ReportMetric(key, value) for key, value in data.valuation.metrics if value is not None),
                provenance=(data.valuation.provenance,), warnings=data.valuation.quality.warnings,
            )
        if data.estimates is not None and data.estimates.provenance is not None and any(value is not None for _, value in data.estimates.metrics):
            sections["estimates"] = ReportSection(
                "estimates", "Analyst Consensus",
                metrics=tuple(ReportMetric(key, value) for key, value in data.estimates.metrics if value is not None),
                provenance=(data.estimates.provenance,), warnings=data.estimates.quality.warnings,
            )
        if data.crypto is not None and any(value is not None for value in (
            data.crypto.market_cap, data.crypto.circulating_supply,
            data.crypto.total_supply, data.crypto.max_supply,
        )):
            sections["market_structure"] = ReportSection(
                "market_structure", "Market Structure",
                metrics=tuple(
                    ReportMetric(key, value, unit=unit)
                    for key, value, unit in (
                        ("crypto_market_cap", data.crypto.market_cap, data.crypto.market_cap_currency or "unknown"),
                        ("crypto_circulating_supply", data.crypto.circulating_supply, "asset units"),
                        ("crypto_total_supply", data.crypto.total_supply, "asset units"),
                        ("crypto_max_supply", data.crypto.max_supply, "asset units"),
                    ) if value is not None
                ),
                provenance=(data.crypto.provenance,), warnings=data.crypto.quality.warnings,
            )
        if data.asset.asset_type is CanonicalAssetType.ETF and data.valuation is not None and "valuation" in sections:
            valuation = sections.pop("valuation")
            sections["fund_market_characteristics"] = ReportSection("fund_market_characteristics", "Fund / Market Characteristics", metrics=valuation.metrics, provenance=valuation.provenance, warnings=valuation.warnings)
        if data.asset.asset_type is CanonicalAssetType.ETF and data.fund_profile is not None:
            fund = data.fund_profile
            metrics = []
            percent_points = lambda value: value * Decimal("100") if value is not None else None
            for key, value, unit in (
                ("assets_under_management", fund.assets_under_management, fund.assets_under_management_currency),
                ("nav", fund.nav, fund.nav_currency),
                ("expense_ratio", percent_points(fund.expense_ratio), "%"),
                ("distribution_yield", percent_points(fund.distribution_yield), "%"),
                ("dividend_yield", percent_points(fund.dividend_yield), "%"),
                ("dividend_yield_ttm", percent_points(fund.dividend_yield_ttm), "%"),
                ("dividend_rate_ttm", fund.dividend_rate_ttm, "unknown"),
            ):
                if value is not None:
                    metrics.append(ReportMetric(key, value, unit=unit))
            details = tuple((key, value) for key, value in (
                ("name", fund.name), ("issuer", fund.issuer), ("fund_family", fund.fund_family),
                ("sponsor", fund.sponsor), ("trustee", fund.trustee),
                ("investment_geography", fund.investment_geography),
                ("objective", fund.objective), ("description", fund.description),
                ("benchmark", fund.benchmark),
                ("distribution_frequency", fund.distribution_frequency),
                ("replication_method", fund.replication_method),
                ("listing_currency", fund.currency), ("exchange", fund.exchange),
                ("provider_fund_inception_date", fund.inception_date.isoformat() if fund.inception_date else None),
                ("assets_under_management_basis", "Provider-reported total assets; currency not separately supplied" if fund.assets_under_management is not None and not fund.assets_under_management_currency else None),
                ("nav_basis", "Provider-reported NAV; currency not separately supplied" if fund.nav is not None and not fund.nav_currency else None),
                ("website", fund.website),
                ("assets_under_management_as_of", fund.assets_under_management_as_of.isoformat() if fund.assets_under_management_as_of else None),
                ("nav_as_of", fund.nav_as_of.isoformat() if fund.nav_as_of else None),
                ("distribution_yield_as_of", fund.distribution_yield_as_of.isoformat() if fund.distribution_yield_as_of else None),
            ) if value is not None)
            sections["fund_characteristics"] = ReportSection(
                "fund_characteristics", "Fund Characteristics", metrics=tuple(metrics),
                provenance=(fund.provenance,), warnings=fund.quality.warnings, details=details,
            )
        if data.fund_profile_secondary is not None:
            fund = data.fund_profile_secondary
            sections["fund_provider_observations"] = ReportSection(
                "fund_provider_observations", "Additional fund-provider observations",
                metrics=tuple(ReportMetric(key, value, unit=unit) for key, value, unit in (
                    ("dividend_yield", fund.dividend_yield * 100 if fund.dividend_yield is not None else None, "%"),
                    ("dividend_yield_ttm", fund.dividend_yield_ttm * 100 if fund.dividend_yield_ttm is not None else None, "%"),
                    ("dividend_rate_ttm", fund.dividend_rate_ttm, "unknown"),
                ) if value is not None),
                provenance=(fund.provenance,),
                details=(("fund_family", fund.fund_family),) if fund.fund_family else (),
            )
        return sections

    @staticmethod
    def _section(key: str, title: str, findings: Sequence[ResearchFinding]) -> ReportSection:
        provenance = tuple(provenance for finding in findings for provenance in finding.provenance)
        warnings = tuple(warning for finding in findings for warning in finding.quality.warnings)
        metrics = tuple(
            ReportMetric(
                finding.evidence.metric,
                finding.evidence.current_value,
                finding.evidence.previous_value,
                finding_id=finding.id,
                period=finding.evidence.comparison_period,
            )
            for finding in findings
        )
        return ReportSection(key, title, tuple(findings), metrics, warnings, provenance)

    def _snapshot(self, data: AssetResearchData, selected: Sequence[ResearchFinding]) -> ReportSection:
        metrics: list[ReportMetric] = []
        provenance: list[ResearchProvenance] = []
        if data.quote is not None:
            for key, value in (
                ("last_price", data.quote.last_price),
                ("previous_close", data.quote.previous_close),
                ("year_high", data.quote.year_high),
                ("year_low", data.quote.year_low),
            ):
                if value is not None:
                    metrics.append(ReportMetric(key, value, unit=data.quote.currency))
            provenance.append(data.quote.provenance)
        elif data.prices is not None and data.prices.bars and data.prices.bars[-1].close is not None:
            metrics.append(ReportMetric("last_price", data.prices.bars[-1].close, unit=data.prices.currency))
            provenance.append(data.prices.provenance)
        elif data.crypto is not None and data.crypto.price_history.bars and data.crypto.price_history.bars[-1].close is not None:
            metrics.append(ReportMetric("last_price", data.crypto.price_history.bars[-1].close, unit=data.crypto.price_history.currency))
            provenance.append(data.crypto.provenance)
        return ReportSection("snapshot", "Snapshot", tuple(selected[:1]), tuple(metrics), provenance=tuple(provenance))

    def _coverage(self, data: AssetResearchData) -> tuple[ReportDataCoverage, ...]:
        sections = [
            ("quote", data.quote), ("prices", data.prices), ("profile", data.profile), ("fundamentals", data.fundamentals),
            ("valuation", data.valuation), ("earnings", data.earnings), ("estimates", data.estimates), ("crypto_market", data.crypto),
            ("filings", data.filings), ("news", data.news), ("fund_info", data.fund_profile),
        ]
        failures = defaultdict(list)
        for failure in data.failures:
            failures[failure.section.split(".")[0]].append(failure)
        coverage: list[ReportDataCoverage] = []
        for name, section in sections:
            if section is None:
                availability = Availability.UPSTREAM_ERROR if name in failures else Availability.NOT_REQUESTED
                coverage.append(ReportDataCoverage(
                    name, availability, FreshnessStatus.UNKNOWN,
                    tuple(item.message for item in failures[name]), failures=tuple(failures[name]),
                ))
                continue
            availability = getattr(section, "availability", section.quality.availability)
            warnings = list(section.quality.warnings) + [item.message for item in failures[name]]
            if name == "fund_info" and section is not None and not self._has_fund_information(section):
                availability = Availability.MISSING
                warnings.append("The provider returned no fund information fields.")
            if section.freshness is FreshnessStatus.STALE:
                warnings.append(f"{name} data is stale.")
            elif section.quality.status is QualityStatus.PARTIAL:
                warnings.append(f"{name} data is partial.")
            elif section.quality.status is QualityStatus.EMPTY:
                warnings.append(f"{name} data is empty.")
            coverage.append(ReportDataCoverage(
                name, availability, section.freshness, tuple(warnings),
                missing_fields=section.quality.missing_fields,
                failures=tuple(failures[name]),
                reference_url=section.website if name == "fund_info" else None,
            ))
        if data.asset.asset_type is CanonicalAssetType.CRYPTO:
            coverage.append(ReportDataCoverage("derivatives_metadata", Availability.NOT_SUPPORTED, FreshnessStatus.UNKNOWN, ("Phase 2 does not provide derivatives metadata.",)))
            crypto = data.crypto
            crypto_info_failures = tuple(failures["crypto_info"])
            for field, value in (
                ("crypto_market_cap", crypto.market_cap if crypto else None),
                ("crypto_circulating_supply", crypto.circulating_supply if crypto else None),
                ("crypto_total_supply", crypto.total_supply if crypto else None),
                ("crypto_max_supply", crypto.max_supply if crypto else None),
            ):
                availability = (
                    Availability.AVAILABLE if value is not None
                    else Availability.UPSTREAM_ERROR if crypto_info_failures
                    else Availability.NOT_REQUESTED if crypto is None
                    else Availability.MISSING
                )
                coverage.append(ReportDataCoverage(
                    field, availability, crypto.freshness if crypto else FreshnessStatus.UNKNOWN,
                    () if value is not None else (
                        tuple(item.message for item in crypto_info_failures)
                        if crypto_info_failures else ("The provider did not return this field.",)
                    ),
                    failures=crypto_info_failures if value is None else (),
                ))
        if data.asset.asset_type is CanonicalAssetType.ETF:
            fund = data.fund_profile
            if fund is None:
                failure = failures["fund_info"]
                availability = Availability.UPSTREAM_ERROR if failure else Availability.NOT_REQUESTED
                coverage.append(ReportDataCoverage("fund_fee", availability, FreshnessStatus.UNKNOWN,
                    tuple(item.message for item in failure), failures=tuple(failure)))
                coverage.append(ReportDataCoverage("fund_aum", availability, FreshnessStatus.UNKNOWN,
                    tuple(item.message for item in failure), failures=tuple(failure)))
                coverage.append(ReportDataCoverage("fund_objective", availability, FreshnessStatus.UNKNOWN,
                    tuple(item.message for item in failure), failures=tuple(failure)))
                coverage.append(ReportDataCoverage("fund_description", availability, FreshnessStatus.UNKNOWN,
                    tuple(item.message for item in failure), failures=tuple(failure)))
                coverage.append(ReportDataCoverage("fund_issuer", availability, FreshnessStatus.UNKNOWN,
                    tuple(item.message for item in failure), failures=tuple(failure)))
                coverage.append(ReportDataCoverage("fund_benchmark", availability, FreshnessStatus.UNKNOWN,
                    tuple(item.message for item in failure), failures=tuple(failure)))
                coverage.append(ReportDataCoverage("fund_distribution", availability, FreshnessStatus.UNKNOWN,
                    tuple(item.message for item in failure), failures=tuple(failure)))
                coverage.append(ReportDataCoverage("fund_replication", availability, FreshnessStatus.UNKNOWN,
                    tuple(item.message for item in failure), failures=tuple(failure)))
            else:
                def field_status(value, *, provider_limited=False):
                    if value is not None:
                        return Availability.AVAILABLE
                    return Availability.NOT_SUPPORTED if provider_limited and fund.provenance.provider == "yfinance" else Availability.MISSING

                coverage.extend((
                    ReportDataCoverage("fund_fee", field_status(fund.expense_ratio, provider_limited=True), fund.freshness, reference_url=fund.website),
                    ReportDataCoverage("fund_aum", field_status(fund.assets_under_management), fund.freshness, reference_url=fund.website),
                    ReportDataCoverage("fund_objective", field_status(fund.objective, provider_limited=True), fund.freshness, reference_url=fund.website),
                    ReportDataCoverage("fund_description", field_status(fund.description), fund.freshness, reference_url=fund.website),
                    ReportDataCoverage("fund_issuer", field_status(fund.issuer), fund.freshness, reference_url=fund.website),
                    ReportDataCoverage("fund_benchmark", field_status(fund.benchmark, provider_limited=True), fund.freshness, reference_url=fund.website),
                    ReportDataCoverage("fund_distribution", field_status(fund.distribution_frequency, provider_limited=True), fund.freshness, reference_url=fund.website),
                    ReportDataCoverage("fund_replication", field_status(fund.replication_method, provider_limited=True), fund.freshness, reference_url=fund.website),
                ))
            composition = data.fund_composition
            for key, values in (("fund_holdings", composition.holdings if composition else ()), ("fund_sectors", composition.sectors if composition else ())):
                failure = tuple(failures["fund_composition"])
                availability = Availability.AVAILABLE if values else (Availability.UPSTREAM_ERROR if failure else Availability.MISSING)
                coverage.append(ReportDataCoverage(
                    key, availability, composition.freshness if composition else FreshnessStatus.UNKNOWN,
                    composition.quality.warnings if composition else tuple(item.message for item in failure),
                    failures=failure, reference_url=fund.website if fund else None,
                ))
            if fund is not None and fund.investment_geography:
                coverage.append(ReportDataCoverage("fund_investment_geography", Availability.AVAILABLE, fund.freshness, reference_url=fund.website))
            unsupported = ("fund_geography",)
            coverage.extend(ReportDataCoverage(
                name, Availability.NOT_SUPPORTED, FreshnessStatus.UNKNOWN,
                (("Country allocation weights are not supplied; the issuer investment geography is a classification, not a weighted country breakdown." if fund is not None and fund.investment_geography else "No credentials-free installed provider is wired for this breakdown."),),
                reference_url=fund.website if fund is not None else None,
            ) for name in unsupported)
        return tuple(coverage)

    @staticmethod
    def _sources(data: AssetResearchData, findings: Iterable[ResearchFinding]) -> tuple[ReportSource, ...]:
        provenance: list[ResearchProvenance] = []
        for section in (data.quote, data.prices, data.profile, data.fundamentals, data.valuation, data.earnings, data.estimates, data.filings, data.news, data.crypto, data.fund_profile, data.fund_composition, data.fund_profile_secondary):
            if section is not None and section.provenance is not None:
                provenance.append(section.provenance)
        if data.crypto is not None and data.crypto.price_history.provenance is not None:
            provenance.append(data.crypto.price_history.provenance)
        provenance.extend(item for finding in findings for item in finding.provenance)
        unique = {(item.provider, item.source_category, item.retrieved_at): item for item in provenance}
        return tuple(ReportSource(provider, category, retrieved_at, unique[(provider, category, retrieved_at)].attempts) for provider, category, retrieved_at in sorted(unique))

    @staticmethod
    def _warnings(data, analysis, coverage, missing_essentials=()) -> tuple[str, ...]:
        warnings = list(data.quality.warnings) + list(analysis.warnings)
        warnings.extend(warning for item in coverage for warning in item.warnings)
        if missing_essentials:
            warnings.append("Report is partial because essential data is unavailable: " + ", ".join(missing_essentials) + ".")
        return tuple(sorted(set(warnings)))

    @staticmethod
    def _missing_essentials(data: AssetResearchData, coverage: Sequence[ReportDataCoverage]) -> tuple[str, ...]:
        missing: list[str] = []
        if data.asset.asset_type is CanonicalAssetType.EQUITY:
            if data.prices is None or not data.prices.bars:
                missing.append("prices")
            if data.fundamentals is None or not data.fundamentals.statements:
                missing.append("fundamentals")
        elif data.asset.asset_type is CanonicalAssetType.ETF:
            if data.prices is None or not data.prices.bars:
                missing.append("prices")
            if data.fund_profile is None or not AssetResearchReportService._has_fund_information(data.fund_profile):
                missing.append("fund_info")
            if data.fund_profile is None or data.fund_profile.expense_ratio is None:
                missing.append("fund_fee")
            if next((row.availability for row in coverage if row.section == "fund_holdings"), Availability.NOT_SUPPORTED) is not Availability.AVAILABLE:
                missing.append("fund_holdings")
        elif data.asset.asset_type is CanonicalAssetType.CRYPTO:
            if data.crypto is None or not data.crypto.price_history.bars:
                missing.append("prices")
            crypto = data.crypto
            if crypto is None or crypto.market_cap is None:
                missing.append("crypto_market_cap")
            if crypto is None or crypto.circulating_supply is None:
                missing.append("crypto_circulating_supply")
            if crypto is None or crypto.total_supply is None:
                missing.append("crypto_total_supply")
        return tuple(sorted(missing))

    @staticmethod
    def _has_fund_information(fund) -> bool:
        return any(value is not None for value in (
            fund.name, fund.issuer, fund.fund_family, fund.objective, fund.description, fund.benchmark,
            fund.expense_ratio, fund.assets_under_management, fund.nav,
            fund.distribution_frequency, fund.dividend_yield,
            fund.dividend_yield_ttm, fund.dividend_rate_ttm, fund.replication_method,
        ))

    @staticmethod
    def _report_quality(
        quality: DataQuality,
        missing: Sequence[str],
        coverage: Sequence[ReportDataCoverage] = (),
    ) -> DataQuality:
        degraded_coverage = any(
            item.availability is Availability.UPSTREAM_ERROR
            or item.freshness is FreshnessStatus.STALE
            for item in coverage
        )
        if (not missing and not degraded_coverage) or quality.status is not QualityStatus.COMPLETE:
            return quality
        reason = "Essential report data is unavailable." if missing else "Requested report data is stale or unavailable upstream."
        return replace(
            quality,
            status=QualityStatus.PARTIAL,
            warnings=quality.warnings + (reason,),
            missing_fields=quality.missing_fields + tuple(missing),
        )

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
        # Earnings ``as_of`` may be a future scheduled report date, not an
        # observation timestamp, so it must not advance the report clock.
        values = [getattr(section, "as_of", None) for section in (data.quote, data.prices, data.profile, data.fundamentals, data.valuation, data.estimates, data.filings, data.news, data.crypto, data.fund_profile) if section is not None]
        values.extend(finding.as_of for finding in findings)
        return max((item for item in values if item is not None), default=None)
