from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal

from app.trading.research.canonical import (
    AssetIdentity,
    AssetResearchData,
    CanonicalAssetType,
    DataQuality,
    FreshnessStatus,
    MacroObservation,
    MacroSeries,
    QualityStatus,
    ResearchProvenance,
)
from app.trading.research.findings import FindingCategory, FindingDirection, FindingEvidence, FindingType, ResearchFinding
from app.trading.research.relevance import ResearchRelevanceEngine
from app.trading.research.serialization import canonical_json
from tests.trading.fixtures import NOW, crypto_price_volume_case, equity_growth_case, partial_data_case


def test_change_acceleration_and_growth_cash_divergence_are_structured():
    findings = ResearchRelevanceEngine().analyze(equity_growth_case()).findings

    revenue = [item for item in findings if item.metric == "revenue"]
    assert {item.finding_type for item in revenue} == {FindingType.CHANGE, FindingType.ACCELERATION}
    assert all(item.evidence.current_value is not None and item.evidence.previous_value is not None for item in revenue)
    assert any(item.metric == "revenue_free_cash_flow" and item.finding_type is FindingType.DIVERGENCE for item in findings)


def test_price_volume_divergence_and_crypto_category_are_supported():
    findings = ResearchRelevanceEngine().analyze(crypto_price_volume_case()).findings

    assert any(item.category is FindingCategory.CRYPTO_MARKET for item in findings)
    assert any(item.metric == "price_volume" and item.finding_type is FindingType.DIVERGENCE for item in findings)


def test_historical_extreme_is_detected_but_insufficient_history_is_silent():
    engine = ResearchRelevanceEngine()
    rich = engine.analyze(equity_growth_case()).findings
    assert any(item.metric == "close_price" and item.finding_type is FindingType.HISTORICAL_EXTREME for item in rich)

    short = equity_growth_case()
    prices = replace(short.prices, bars=short.prices.bars[-2:])
    sparse = engine.analyze(replace(short, prices=prices)).findings
    assert not any(item.metric == "close_price" and item.finding_type is FindingType.HISTORICAL_EXTREME for item in sparse)


def test_materiality_guard_does_not_promote_tiny_large_percentage_change():
    data = partial_data_case()
    tiny = tuple(replace(bar, close=Decimal("0.0001") if index == 0 else Decimal("0.0002")) for index, bar in enumerate(data.prices.bars[-2:]))
    result = ResearchRelevanceEngine().analyze(replace(data, prices=replace(data.prices, bars=tiny)))
    assert not any(item.metric == "close_price" and item.finding_type is FindingType.CHANGE for item in result.findings)


def test_partial_and_stale_data_reduce_confidence_and_emit_quality_findings():
    engine = ResearchRelevanceEngine()
    complete = engine.analyze(equity_growth_case())
    partial = engine.analyze(partial_data_case())
    stale_source = equity_growth_case()
    stale = engine.analyze(replace(stale_source, prices=replace(stale_source.prices, freshness=FreshnessStatus.STALE, quality=DataQuality(QualityStatus.STALE))))

    complete_price = next(item for item in complete.findings if item.metric == "close_price" and item.finding_type is FindingType.CHANGE)
    partial_price = next(item for item in partial.findings if item.metric == "close_price" and item.finding_type is FindingType.CHANGE)
    assert partial_price.confidence < complete_price.confidence
    assert any(item.finding_type is FindingType.DATA_GAP for item in partial.findings)
    assert any(item.finding_type is FindingType.STALE_DATA for item in stale.findings)


def test_missing_data_is_not_zero_and_unsupported_sections_create_no_financial_finding():
    asset = AssetIdentity("EMPTY", CanonicalAssetType.EQUITY)
    data = AssetResearchData(asset, quality=DataQuality(QualityStatus.EMPTY))
    result = ResearchRelevanceEngine().analyze(data)
    assert result.findings == ()


def test_more_unusual_finding_ranks_above_mundane_change_and_is_deterministic():
    engine = ResearchRelevanceEngine()
    data = equity_growth_case()
    first = engine.analyze(data)
    second = engine.analyze(data)
    extreme = next(item for item in first.findings if item.metric == "close_price" and item.finding_type is FindingType.HISTORICAL_EXTREME)
    change = next(item for item in first.findings if item.metric == "close_price" and item.finding_type is FindingType.CHANGE)
    assert extreme.relevance_score > change.relevance_score
    assert canonical_json(first) == canonical_json(second)
    assert [item.id for item in first.top_findings] == [item.id for item in second.top_findings]


def test_equivalent_valuation_candidates_collapse_and_top_selection_is_diverse():
    engine = ResearchRelevanceEngine()
    asset = AssetIdentity("VAL", CanonicalAssetType.EQUITY)
    provenance = ResearchProvenance("fixture", "valuation", NOW)
    base = dict(asset=asset, category=FindingCategory.VALUATION, metric="pe_ratio", theme="valuation", relevance_score=Decimal("0.8"), confidence=Decimal("0.9"), direction=FindingDirection.UP, evidence=FindingEvidence("pe_ratio", Decimal("40"), history_size=5), context=(), provenance=(provenance,), quality=DataQuality(QualityStatus.COMPLETE), as_of=NOW, relevance_components=(("magnitude", Decimal("0.8")),))
    candidates = (
        ResearchFinding(id="first", finding_type=FindingType.HISTORICAL_EXTREME, **base),
        ResearchFinding(id="second", finding_type=FindingType.ANOMALY, **base),
    )
    assert len(engine.deduplicate(candidates)) == 1
    top = engine.analyze(equity_growth_case()).top_findings
    assert len([item for item in top if item.category is FindingCategory.GROWTH]) <= engine.policy.max_per_category


def test_conflicting_price_and_fundamental_directions_are_linked_without_rating():
    data = equity_growth_case()
    # A falling price versus rising revenue creates a qualified evidence conflict.
    bars = tuple(replace(bar, close=Decimal("120") if index == len(data.prices.bars) - 2 else Decimal("90")) for index, bar in enumerate(data.prices.bars))
    result = ResearchRelevanceEngine().analyze(replace(data, prices=replace(data.prices, bars=bars)))
    price = next(item for item in result.findings if item.metric == "close_price" and item.finding_type is FindingType.CHANGE)
    revenue = next(item for item in result.findings if item.metric == "revenue" and item.finding_type is FindingType.CHANGE)
    assert price.direction is FindingDirection.DOWN
    assert revenue.id in price.conflicts_with and price.id in revenue.conflicts_with


def test_macro_change_and_extreme_are_provider_independent():
    asset = AssetIdentity("CPI", CanonicalAssetType.MACRO_SERIES)
    observations = tuple(MacroObservation(datetime(2026, month, 1, tzinfo=timezone.utc), Decimal(value)) for month, value in enumerate((100, 101, 102, 103, 104, 115), start=1))
    macro = MacroSeries(asset, observations, "index", "month", ResearchProvenance("fixture", "macro_series", NOW), observations[-1].timestamp, FreshnessStatus.FRESH, DataQuality(QualityStatus.COMPLETE))
    findings = ResearchRelevanceEngine().analyze_macro(macro).findings
    assert {item.category for item in findings} == {FindingCategory.MACRO}
    assert {item.finding_type for item in findings} == {FindingType.CHANGE, FindingType.HISTORICAL_EXTREME}
