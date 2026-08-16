"""Deterministic evaluators and ranking for canonical research data.

All thresholds are held in :class:`RelevancePolicy`; the engine deliberately
reports observed data conditions rather than future-return views.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from hashlib import sha256
from typing import Iterable, Sequence

from .canonical import (
    AssetResearchData,
    Availability,
    DataQuality,
    FinancialStatement,
    FreshnessStatus,
    FundamentalsData,
    MacroSeries,
    PriceSeries,
    QualityStatus,
    ResearchProvenance,
    StatementPeriod,
)
from .findings import (
    FindingCategory,
    FindingDirection,
    FindingEvidence,
    FindingType,
    ResearchAnalysis,
    ResearchFinding,
    ResearchTheme,
)


ZERO = Decimal("0")
ONE = Decimal("1")


def _clamp(value: Decimal) -> Decimal:
    return max(ZERO, min(ONE, value))


def _decimal_ratio(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    return None if denominator == ZERO else numerator / denominator


def _rounded(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True, slots=True)
class RelevancePolicy:
    """Small, explicit tuning boundary for Phase-3 deterministic rules."""

    price_change_threshold: Decimal = Decimal("0.05")
    crypto_price_change_threshold: Decimal = Decimal("0.08")
    fundamental_change_threshold: Decimal = Decimal("0.08")
    margin_change_threshold: Decimal = Decimal("0.02")
    macro_change_threshold: Decimal = Decimal("0.05")
    volume_spike_threshold: Decimal = Decimal("0.50")
    weak_participation_threshold: Decimal = Decimal("0.20")
    earnings_surprise_threshold: Decimal = Decimal("0.05")
    minimum_material_value: Decimal = Decimal("1")
    minimum_history_for_extreme: int = 5
    high_percentile_cutoff: Decimal = Decimal("0.90")
    low_percentile_cutoff: Decimal = Decimal("0.10")
    minimum_history_for_acceleration: int = 3
    acceleration_delta_threshold: Decimal = Decimal("0.03")
    max_findings: int = 5
    max_per_category: int = 2
    score_weights: tuple[tuple[str, Decimal], ...] = (
        ("magnitude", Decimal("0.35")),
        ("rarity", Decimal("0.25")),
        ("recency", Decimal("0.15")),
        ("materiality", Decimal("0.15")),
        ("quality", Decimal("0.10")),
    )

    def __post_init__(self) -> None:
        if self.minimum_history_for_extreme < 2 or self.minimum_history_for_acceleration < 3:
            raise ValueError("history requirements are too small")
        if self.max_findings < 1 or self.max_per_category < 1:
            raise ValueError("finding limits must be positive")
        if sum(value for _, value in self.score_weights) != ONE:
            raise ValueError("score weights must sum to 1")


_QUALITY_SCORE = {
    QualityStatus.COMPLETE: ONE,
    QualityStatus.PARTIAL: Decimal("0.70"),
    QualityStatus.STALE: Decimal("0.50"),
    QualityStatus.EMPTY: ZERO,
    QualityStatus.ERROR: ZERO,
}
_FRESHNESS_SCORE = {
    FreshnessStatus.FRESH: ONE,
    FreshnessStatus.STALE: Decimal("0.50"),
    FreshnessStatus.UNKNOWN: Decimal("0.65"),
}


def _quality_component(quality: DataQuality) -> Decimal:
    return _QUALITY_SCORE[quality.status]


def _confidence(quality: DataQuality, freshness: FreshnessStatus, history_size: int, policy: RelevancePolicy) -> Decimal:
    """Evidence sufficiency, not a probability of any future market outcome."""
    history = _clamp(Decimal(history_size) / Decimal(policy.minimum_history_for_extreme))
    return _rounded(
        Decimal("0.45") * _quality_component(quality)
        + Decimal("0.35") * history
        + Decimal("0.20") * _FRESHNESS_SCORE[freshness]
    )


def _direction(change: Decimal | None) -> FindingDirection:
    if change is None:
        return FindingDirection.UNKNOWN
    if change > ZERO:
        return FindingDirection.UP
    if change < ZERO:
        return FindingDirection.DOWN
    return FindingDirection.NEUTRAL


def _percentile(values: Sequence[Decimal], current: Decimal) -> Decimal:
    return Decimal(sum(value <= current for value in values)) / Decimal(len(values))


def _score(
    *,
    magnitude: Decimal,
    rarity: Decimal,
    materiality: Decimal,
    quality: DataQuality,
    policy: RelevancePolicy,
) -> tuple[Decimal, tuple[tuple[str, Decimal], ...]]:
    components = {
        "magnitude": _clamp(magnitude),
        "rarity": _clamp(rarity),
        "recency": ONE,
        "materiality": _clamp(materiality),
        "quality": _quality_component(quality),
    }
    weights = dict(policy.score_weights)
    score = _rounded(sum(components[key] * weights[key] for key in components))
    return score, tuple(sorted((key, _rounded(value)) for key, value in components.items()))


def _finding_id(asset_symbol: str, category: FindingCategory, finding_type: FindingType, metric: str, as_of: datetime | None) -> str:
    stable = "|".join((asset_symbol, category.value, finding_type.value, metric, as_of.isoformat() if as_of else ""))
    return f"rf_{sha256(stable.encode()).hexdigest()[:16]}"


def _statement_values(fundamentals: FundamentalsData, statement_type: str, metric: str) -> list[tuple[datetime, Decimal]]:
    values: list[tuple[datetime, Decimal]] = []
    for statement in fundamentals.statements:
        if statement.statement_type != statement_type or statement.period is StatementPeriod.OTHER or statement.period_end is None:
            continue
        value = dict(statement.values).get(metric)
        if value is not None:
            values.append((statement.period_end, value))
    return sorted(values)


class ResearchRelevanceEngine:
    """Turns Phase-2 canonical data into reproducible, non-predictive findings."""

    def __init__(self, policy: RelevancePolicy | None = None) -> None:
        self.policy = policy or RelevancePolicy()

    def analyze(self, asset_data: AssetResearchData) -> ResearchAnalysis:
        candidates: list[ResearchFinding] = []
        if asset_data.prices is not None:
            candidates.extend(self._evaluate_prices(asset_data.prices, crypto=False))
        if asset_data.crypto is not None and asset_data.prices is None:
            candidates.extend(self._evaluate_prices(asset_data.crypto.price_history, crypto=True))
        if asset_data.fundamentals is not None:
            candidates.extend(self._evaluate_fundamentals(asset_data.fundamentals))
        if asset_data.earnings is not None:
            candidates.extend(self._evaluate_earnings(asset_data.earnings))
        candidates.extend(self._evaluate_quality(asset_data))
        findings = self._mark_conflicts(self.deduplicate(candidates))
        top = self._select_top(findings, limit=self.policy.max_findings)
        themes = self._themes(findings)
        warnings = tuple(failure.message for failure in asset_data.failures)
        return ResearchAnalysis(
            asset=asset_data.asset,
            findings=tuple(findings),
            top_findings=tuple(top),
            themes=themes,
            warnings=warnings,
            metadata=(("engine", "phase3_deterministic"), ("policy", "default"), ("llm_used", "false")),
        )

    def analyze_macro(self, macro: MacroSeries) -> ResearchAnalysis:
        candidates = self._evaluate_series(
            asset=macro.asset,
            values=[(item.timestamp, item.value) for item in macro.observations if item.value is not None],
            category=FindingCategory.MACRO,
            metric="macro_value",
            theme="macro",
            provenance=(macro.provenance,),
            quality=macro.quality,
            freshness=macro.freshness,
            change_threshold=self.policy.macro_change_threshold,
            comparison_period=macro.frequency or "previous_observation",
        )
        findings = self.deduplicate(candidates)
        return ResearchAnalysis(
            asset=macro.asset,
            findings=tuple(findings),
            top_findings=tuple(self._select_top(findings, limit=self.policy.max_findings)),
            themes=self._themes(findings),
            warnings=macro.quality.warnings,
            metadata=(("engine", "phase3_deterministic"), ("analysis", "macro"), ("llm_used", "false")),
        )

    def get_top_findings(self, asset_data: AssetResearchData, *, limit: int = 5) -> tuple[ResearchFinding, ...]:
        if limit < 1:
            raise ValueError("limit must be positive")
        return tuple(self._select_top(self.analyze(asset_data).findings, limit=limit))

    def _make(
        self,
        *,
        asset_data,
        category: FindingCategory,
        finding_type: FindingType,
        metric: str,
        theme: str,
        direction: FindingDirection,
        evidence: FindingEvidence,
        quality: DataQuality,
        freshness: FreshnessStatus,
        provenance: tuple[ResearchProvenance, ...],
        as_of: datetime | None,
        magnitude: Decimal,
        rarity: Decimal = ZERO,
        materiality: Decimal = ONE,
        context: tuple[tuple[str, str], ...] = (),
    ) -> ResearchFinding:
        score, components = _score(magnitude=magnitude, rarity=rarity, materiality=materiality, quality=quality, policy=self.policy)
        return ResearchFinding(
            id=_finding_id(asset_data.symbol, category, finding_type, metric, as_of),
            asset=asset_data,
            category=category,
            finding_type=finding_type,
            metric=metric,
            theme=theme,
            relevance_score=score,
            confidence=_confidence(quality, freshness, evidence.history_size, self.policy),
            direction=direction,
            evidence=evidence,
            context=context,
            provenance=provenance,
            quality=quality,
            as_of=as_of,
            relevance_components=components,
        )

    def _evaluate_prices(self, prices: PriceSeries, *, crypto: bool) -> list[ResearchFinding]:
        category = FindingCategory.CRYPTO_MARKET if crypto else FindingCategory.PRICE
        threshold = self.policy.crypto_price_change_threshold if crypto else self.policy.price_change_threshold
        close_values = [(bar.timestamp, bar.close) for bar in prices.bars if bar.close is not None]
        findings = self._evaluate_series(
            asset=prices.asset, values=close_values, category=category, metric="close_price", theme="price_action",
            provenance=(prices.provenance,), quality=prices.quality, freshness=prices.freshness,
            change_threshold=threshold, comparison_period=prices.interval or "previous_bar",
        )
        volume_values = [(bar.timestamp, bar.volume) for bar in prices.bars if bar.volume is not None]
        if len(volume_values) >= 2:
            current_at, current = volume_values[-1]
            _, previous = volume_values[-2]
            relative = _decimal_ratio(current - previous, previous)
            if relative is not None and relative >= self.policy.volume_spike_threshold and previous >= self.policy.minimum_material_value:
                findings.append(self._make(
                    asset_data=prices.asset, category=FindingCategory.VOLUME, finding_type=FindingType.ANOMALY,
                    metric="volume", theme="price_action", direction=FindingDirection.UP,
                    evidence=FindingEvidence("volume", current, previous, current - previous, relative, prices.interval or "previous_bar", len(volume_values), observations=((current_at.isoformat(), current),)),
                    quality=prices.quality, freshness=prices.freshness, provenance=(prices.provenance,), as_of=current_at,
                    magnitude=_clamp(relative / (self.policy.volume_spike_threshold * Decimal("3"))), materiality=ONE,
                ))
            if len(volume_values) >= self.policy.minimum_history_for_extreme:
                percentile = _percentile([value for _, value in volume_values], current)
                if percentile >= self.policy.high_percentile_cutoff:
                    findings.append(self._make(
                        asset_data=prices.asset, category=FindingCategory.VOLUME, finding_type=FindingType.HISTORICAL_EXTREME,
                        metric="volume", theme="price_action", direction=FindingDirection.UP,
                        evidence=FindingEvidence("volume", current, history_size=len(volume_values), percentile=percentile, comparison_period="available_history", observations=((current_at.isoformat(), current),)),
                        quality=prices.quality, freshness=prices.freshness, provenance=(prices.provenance,), as_of=current_at,
                        magnitude=percentile, rarity=_clamp((percentile - self.policy.high_percentile_cutoff) / (ONE - self.policy.high_percentile_cutoff)),
                    ))
        # Price/volume divergence needs both complete latest observations.
        if len(close_values) >= 2 and len(volume_values) >= 2 and close_values[-1][0] == volume_values[-1][0]:
            _, close_now = close_values[-1]
            _, close_before = close_values[-2]
            _, volume_now = volume_values[-1]
            _, volume_before = volume_values[-2]
            price_change = _decimal_ratio(close_now - close_before, close_before)
            volume_change = _decimal_ratio(volume_now - volume_before, volume_before)
            opposing = (
                price_change is not None and volume_change is not None
                and ((price_change >= threshold and volume_change <= -self.policy.weak_participation_threshold)
                     or (price_change <= -threshold and volume_change >= self.policy.weak_participation_threshold))
            )
            if opposing:
                findings.append(self._make(
                    asset_data=prices.asset, category=FindingCategory.CROSS_METRIC, finding_type=FindingType.DIVERGENCE,
                    metric="price_volume", theme="price_action", direction=FindingDirection.MIXED,
                    evidence=FindingEvidence("price_volume", close_now, close_before, close_now - close_before, price_change, prices.interval or "previous_bar", 2, observations=(("volume_change", volume_change),)),
                    quality=prices.quality, freshness=prices.freshness, provenance=(prices.provenance,), as_of=close_values[-1][0],
                    magnitude=_clamp(max(abs(price_change), abs(volume_change))), materiality=ONE,
                    context=(("volume_relative_change", str(_rounded(volume_change))),),
                ))
        return findings

    def _evaluate_series(self, *, asset, values, category, metric, theme, provenance, quality, freshness, change_threshold, comparison_period) -> list[ResearchFinding]:
        values = [(timestamp, value) for timestamp, value in values if value is not None]
        if len(values) < 2:
            return []
        current_at, current = values[-1]
        _, previous = values[-2]
        relative = _decimal_ratio(current - previous, previous)
        results: list[ResearchFinding] = []
        if relative is not None and abs(relative) >= change_threshold and abs(previous) >= self.policy.minimum_material_value:
            results.append(self._make(
                asset_data=asset, category=category, finding_type=FindingType.CHANGE, metric=metric, theme=theme,
                direction=_direction(relative), evidence=FindingEvidence(metric, current, previous, current - previous, relative, comparison_period, len(values), observations=((current_at.isoformat(), current),)),
                quality=quality, freshness=freshness, provenance=provenance, as_of=current_at,
                magnitude=_clamp(abs(relative) / (change_threshold * Decimal("3"))), materiality=ONE,
            ))
        if len(values) >= self.policy.minimum_history_for_extreme:
            percentile = _percentile([value for _, value in values], current)
            high = percentile >= self.policy.high_percentile_cutoff
            low = percentile <= self.policy.low_percentile_cutoff
            if high or low:
                rarity = ((percentile - self.policy.high_percentile_cutoff) / (ONE - self.policy.high_percentile_cutoff)) if high else ((self.policy.low_percentile_cutoff - percentile) / self.policy.low_percentile_cutoff)
                results.append(self._make(
                    asset_data=asset, category=category, finding_type=FindingType.HISTORICAL_EXTREME, metric=metric, theme=theme,
                    direction=FindingDirection.UP if high else FindingDirection.DOWN,
                    evidence=FindingEvidence(metric, current, history_size=len(values), percentile=percentile, comparison_period="available_history", observations=((current_at.isoformat(), current),)),
                    quality=quality, freshness=freshness, provenance=provenance, as_of=current_at,
                    magnitude=max(percentile, ONE - percentile), rarity=rarity,
                ))
        return results

    def _evaluate_fundamentals(self, fundamentals: FundamentalsData) -> list[ResearchFinding]:
        findings: list[ResearchFinding] = []
        concepts = (
            ("income", "revenue", FindingCategory.GROWTH, "growth"),
            ("income", "operating_income", FindingCategory.PROFITABILITY, "profitability"),
            ("income", "net_income", FindingCategory.PROFITABILITY, "profitability"),
            ("balance", "total_debt", FindingCategory.BALANCE_SHEET, "balance_sheet"),
            ("cash_flow", "free_cash_flow", FindingCategory.CASH_FLOW, "cash_flow"),
            ("cash_flow", "operating_cash_flow", FindingCategory.CASH_FLOW, "cash_flow"),
        )
        for statement_type, metric, category, theme in concepts:
            # Never compare annual values with quarterly or TTM values.
            for period in (StatementPeriod.ANNUAL, StatementPeriod.QUARTERLY, StatementPeriod.TTM):
                values = [(timestamp, value) for timestamp, value in _statement_values(fundamentals, statement_type, metric)
                          if any(item.statement_type == statement_type and item.period_end == timestamp and item.period is period for item in fundamentals.statements)]
                findings.extend(self._evaluate_fundamental_metric(fundamentals, values, metric, category, theme, period))
        # Operating margin is a derived ratio only when revenue and income share the exact period end and semantics.
        margin_values: list[tuple[datetime, Decimal]] = []
        for statement in fundamentals.statements:
            values = dict(statement.values)
            revenue, operating_income = values.get("revenue"), values.get("operating_income")
            if statement.statement_type == "income" and statement.period is not StatementPeriod.OTHER and statement.period_end and revenue not in (None, ZERO) and operating_income is not None:
                margin_values.append((statement.period_end, operating_income / revenue))
        for period in (StatementPeriod.ANNUAL, StatementPeriod.QUARTERLY, StatementPeriod.TTM):
            eligible = [(timestamp, value) for timestamp, value in margin_values if any(item.statement_type == "income" and item.period_end == timestamp and item.period is period for item in fundamentals.statements)]
            findings.extend(self._evaluate_fundamental_metric(fundamentals, eligible, "operating_margin", FindingCategory.PROFITABILITY, "profitability", period, is_margin=True))
        findings.extend(self._growth_cash_divergence(fundamentals))
        return findings

    def _evaluate_fundamental_metric(self, fundamentals, values, metric, category, theme, period, *, is_margin=False) -> list[ResearchFinding]:
        if len(values) < 2:
            return []
        current_at, current = values[-1]
        _, previous = values[-2]
        absolute = current - previous
        relative = _decimal_ratio(absolute, previous)
        threshold = self.policy.margin_change_threshold if is_margin else self.policy.fundamental_change_threshold
        meaningful = abs(absolute) >= threshold if is_margin else (relative is not None and abs(relative) >= threshold and abs(previous) >= self.policy.minimum_material_value)
        results: list[ResearchFinding] = []
        if meaningful:
            magnitude_basis = abs(absolute) / (threshold * Decimal("3")) if is_margin else abs(relative) / (threshold * Decimal("3"))
            results.append(self._make(
                asset_data=fundamentals.asset, category=category, finding_type=FindingType.CHANGE, metric=metric, theme=theme,
                direction=_direction(absolute), evidence=FindingEvidence(metric, current, previous, absolute, relative, period.value, len(values), observations=((current_at.isoformat(), current),)),
                quality=fundamentals.quality, freshness=fundamentals.freshness, provenance=(fundamentals.provenance,), as_of=current_at,
                magnitude=_clamp(magnitude_basis), materiality=ONE,
            ))
        if len(values) >= self.policy.minimum_history_for_acceleration:
            first_change = _decimal_ratio(values[-2][1] - values[-3][1], values[-3][1])
            latest_change = _decimal_ratio(current - previous, previous)
            if first_change is not None and latest_change is not None:
                acceleration = latest_change - first_change
                if abs(acceleration) >= self.policy.acceleration_delta_threshold:
                    results.append(self._make(
                        asset_data=fundamentals.asset, category=category,
                        finding_type=FindingType.ACCELERATION if acceleration > ZERO else FindingType.DECELERATION,
                        metric=metric, theme=theme, direction=_direction(acceleration),
                        evidence=FindingEvidence(metric, current, previous, absolute, latest_change, period.value, len(values), observations=(("previous_change", first_change), ("latest_change", latest_change))),
                        quality=fundamentals.quality, freshness=fundamentals.freshness, provenance=(fundamentals.provenance,), as_of=current_at,
                        magnitude=_clamp(abs(acceleration) / (self.policy.acceleration_delta_threshold * Decimal("3"))), materiality=ONE,
                    ))
        return results

    def _growth_cash_divergence(self, fundamentals: FundamentalsData) -> list[ResearchFinding]:
        results: list[ResearchFinding] = []
        for period in (StatementPeriod.ANNUAL, StatementPeriod.QUARTERLY, StatementPeriod.TTM):
            revenue = [(date, value) for date, value in _statement_values(fundamentals, "income", "revenue") if any(s.statement_type == "income" and s.period_end == date and s.period is period for s in fundamentals.statements)]
            cash = [(date, value) for date, value in _statement_values(fundamentals, "cash_flow", "free_cash_flow") if any(s.statement_type == "cash_flow" and s.period_end == date and s.period is period for s in fundamentals.statements)]
            if len(revenue) < 2 or len(cash) < 2 or revenue[-1][0] != cash[-1][0]:
                continue
            revenue_change = _decimal_ratio(revenue[-1][1] - revenue[-2][1], revenue[-2][1])
            cash_change = _decimal_ratio(cash[-1][1] - cash[-2][1], cash[-2][1])
            if revenue_change is None or cash_change is None:
                continue
            if revenue_change >= self.policy.fundamental_change_threshold and cash_change <= -self.policy.fundamental_change_threshold:
                results.append(self._make(
                    asset_data=fundamentals.asset, category=FindingCategory.CROSS_METRIC, finding_type=FindingType.DIVERGENCE,
                    metric="revenue_free_cash_flow", theme="fundamentals", direction=FindingDirection.MIXED,
                    evidence=FindingEvidence("revenue_free_cash_flow", revenue[-1][1], revenue[-2][1], revenue[-1][1] - revenue[-2][1], revenue_change, period.value, 2, observations=(("free_cash_flow_change", cash_change),)),
                    quality=fundamentals.quality, freshness=fundamentals.freshness, provenance=(fundamentals.provenance,), as_of=revenue[-1][0],
                    magnitude=_clamp(max(abs(revenue_change), abs(cash_change))), materiality=ONE,
                    context=(("free_cash_flow_relative_change", str(_rounded(cash_change))),),
                ))
        return results

    def _evaluate_earnings(self, earnings) -> list[ResearchFinding]:
        observations = [item for item in earnings.observations if item.reported_eps is not None and item.estimated_eps not in (None, ZERO)]
        if not observations:
            return []
        latest = observations[-1]
        surprise = _decimal_ratio(latest.reported_eps - latest.estimated_eps, latest.estimated_eps)
        if surprise is None or abs(surprise) < self.policy.earnings_surprise_threshold:
            return []
        as_of = latest.earnings_date or latest.period_end
        return [self._make(
            asset_data=earnings.asset, category=FindingCategory.EARNINGS, finding_type=FindingType.ANOMALY,
            metric="eps_surprise", theme="earnings", direction=_direction(surprise),
            evidence=FindingEvidence("eps_surprise", latest.reported_eps, latest.estimated_eps, latest.reported_eps - latest.estimated_eps, surprise, "reported_vs_estimate", len(observations)),
            quality=earnings.quality, freshness=earnings.freshness, provenance=(earnings.provenance,), as_of=as_of,
            magnitude=_clamp(abs(surprise) / (self.policy.earnings_surprise_threshold * Decimal("3"))), materiality=ONE,
        )]

    def _evaluate_quality(self, data: AssetResearchData) -> list[ResearchFinding]:
        findings: list[ResearchFinding] = []
        sections = (("prices", data.prices), ("fundamentals", data.fundamentals), ("valuation", data.valuation), ("earnings", data.earnings), ("crypto", data.crypto))
        for name, section in sections:
            if section is None:
                continue
            if section.quality.status is QualityStatus.STALE or section.freshness is FreshnessStatus.STALE:
                findings.append(self._make(
                    asset_data=data.asset, category=FindingCategory.DATA_QUALITY, finding_type=FindingType.STALE_DATA,
                    metric=name, theme="data_quality", direction=FindingDirection.UNKNOWN,
                    evidence=FindingEvidence(name, comparison_period="freshness", history_size=0), quality=section.quality,
                    freshness=section.freshness, provenance=(section.provenance,), as_of=getattr(section, "as_of", None),
                    magnitude=Decimal("0.50"), materiality=ONE,
                ))
            elif section.quality.status in {QualityStatus.PARTIAL, QualityStatus.EMPTY}:
                findings.append(self._make(
                    asset_data=data.asset, category=FindingCategory.DATA_QUALITY, finding_type=FindingType.DATA_GAP,
                    metric=name, theme="data_quality", direction=FindingDirection.UNKNOWN,
                    evidence=FindingEvidence(name, comparison_period="section_quality", history_size=0), quality=section.quality,
                    freshness=section.freshness, provenance=(section.provenance,), as_of=getattr(section, "as_of", None),
                    magnitude=Decimal("0.35"), materiality=ONE,
                ))
        for failure in data.failures:
            findings.append(self._make(
                asset_data=data.asset, category=FindingCategory.DATA_QUALITY, finding_type=FindingType.DATA_GAP,
                metric=failure.section, theme="data_quality", direction=FindingDirection.UNKNOWN,
                evidence=FindingEvidence(failure.section, comparison_period="upstream_failure"), quality=data.quality,
                freshness=FreshnessStatus.UNKNOWN, provenance=(), as_of=None,
                magnitude=Decimal("0.40"), materiality=ONE, context=(("code", failure.code),),
            ))
        return findings

    def deduplicate(self, candidates: Iterable[ResearchFinding]) -> tuple[ResearchFinding, ...]:
        """Keep the strongest deterministic representative of each finding family."""
        families = {
            FindingType.CHANGE: "change",
            FindingType.ACCELERATION: "trend",
            FindingType.DECELERATION: "trend",
            FindingType.HISTORICAL_EXTREME: "unusual",
            FindingType.ANOMALY: "unusual",
        }
        chosen: dict[tuple[str, str, str], ResearchFinding] = {}
        for finding in candidates:
            key = (finding.category.value, finding.metric, families.get(finding.finding_type, finding.finding_type.value))
            existing = chosen.get(key)
            if existing is None or self._rank_key(finding) < self._rank_key(existing):
                chosen[key] = finding
        return tuple(sorted(chosen.values(), key=self._rank_key))

    def _mark_conflicts(self, findings: Sequence[ResearchFinding]) -> tuple[ResearchFinding, ...]:
        # Only call out directly opposed price and fundamental observations; no directional recommendation is inferred.
        price = [item for item in findings if item.category in {FindingCategory.PRICE, FindingCategory.CRYPTO_MARKET} and item.direction in {FindingDirection.UP, FindingDirection.DOWN}]
        fundamentals = [item for item in findings if item.category in {FindingCategory.GROWTH, FindingCategory.PROFITABILITY, FindingCategory.CASH_FLOW} and item.direction in {FindingDirection.UP, FindingDirection.DOWN}]
        conflicts: dict[str, list[str]] = defaultdict(list)
        for left in price:
            for right in fundamentals:
                if left.direction != right.direction:
                    conflicts[left.id].append(right.id)
                    conflicts[right.id].append(left.id)
        return tuple(replace(item, conflicts_with=tuple(conflicts[item.id])) if item.id in conflicts else item for item in findings)

    def _select_top(self, findings: Sequence[ResearchFinding], *, limit: int) -> list[ResearchFinding]:
        selected: list[ResearchFinding] = []
        per_category: defaultdict[FindingCategory, int] = defaultdict(int)
        for finding in sorted(findings, key=self._rank_key):
            if per_category[finding.category] >= self.policy.max_per_category:
                continue
            selected.append(finding)
            per_category[finding.category] += 1
            if len(selected) == limit:
                break
        return selected

    @staticmethod
    def _rank_key(finding: ResearchFinding) -> tuple[Decimal, Decimal, str]:
        return (-finding.relevance_score, -finding.confidence, finding.id)

    @staticmethod
    def _themes(findings: Sequence[ResearchFinding]) -> tuple[ResearchTheme, ...]:
        grouped: defaultdict[str, list[str]] = defaultdict(list)
        for finding in findings:
            grouped[finding.theme].append(finding.id)
        return tuple(ResearchTheme(key, tuple(ids)) for key, ids in sorted(grouped.items()))
