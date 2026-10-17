from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from app.trading.research.canonical import (
    AssetIdentity,
    AssetResearchData,
    Availability,
    CanonicalAssetType,
    CompanyFiling,
    CompanyFilings,
    CompanyNews,
    DataQuality,
    EarningsData,
    EarningsObservation,
    EstimatesData,
    EquityQuote,
    FreshnessStatus,
    NewsArticle,
    QualityStatus,
    ProviderAttempt,
    PriceBar,
    ResearchProvenance,
    SectionFailure,
    ValuationData,
)
from app.trading.research.findings import FindingCategory
from app.trading.research.relevance import ResearchRelevanceEngine
from app.trading.research.report_service import AssetResearchReportService
from app.trading.research.reports import ReportDataConfidence, ReportDepth
from app.trading.research.serialization import canonical_json, to_jsonable
from tests.trading.fixtures import NOW, crypto_price_volume_case, equity_growth_case, partial_data_case


def _build(data, depth=ReportDepth.STANDARD):
    analysis = ResearchRelevanceEngine().analyze(data)
    return AssetResearchReportService().build_asset_report(research_data=data, analysis=analysis, depth=depth)


def test_full_equity_report_uses_stable_equity_template_and_preserves_evidence():
    data = equity_growth_case()
    valuation = ValuationData(data.asset, (("pe_ratio", Decimal("41.8")),), data.prices.provenance, NOW, FreshnessStatus.FRESH, DataQuality(QualityStatus.COMPLETE))
    report = _build(replace(data, valuation=valuation))

    assert [section.key for section in report.sections] == ["snapshot", "key_findings", "fundamentals", "growth", "profitability", "cash_flow", "valuation", "market_behavior", "risks", "data_quality", "sources"]
    assert report.summary.data_confidence is ReportDataConfidence.HIGH
    assert any(metric.key == "pe_ratio" and metric.value == Decimal("41.8") for section in report.sections if section.key == "valuation" for metric in section.metrics)
    assert all(finding.provenance for finding in report.key_findings)
    assert all(finding.id for finding in report.key_findings)


def test_report_depths_control_presentation_only_and_reuse_phase_three_order():
    data = equity_growth_case()
    analysis = ResearchRelevanceEngine().analyze(data)
    service = AssetResearchReportService()
    brief = service.build_asset_report(research_data=data, analysis=analysis, depth=ReportDepth.BRIEF)
    detailed = service.build_asset_report(research_data=data, analysis=analysis, depth=ReportDepth.DETAILED)

    assert len(brief.key_findings) <= 5
    assert len(detailed.key_findings) >= len(brief.key_findings)
    assert [item.id for item in brief.key_findings] == [item.id for item in analysis.findings[:len(brief.key_findings)]]
    assert brief.as_of == detailed.as_of and brief.generated_at == detailed.generated_at


def test_partial_and_stale_data_are_explicit_caveats_with_lower_confidence():
    partial = _build(partial_data_case())
    stale_source = equity_growth_case()
    stale = _build(replace(stale_source, fundamentals=replace(stale_source.fundamentals, freshness=FreshnessStatus.STALE, quality=DataQuality(QualityStatus.STALE))))

    assert partial.summary.data_confidence is ReportDataConfidence.MEDIUM
    assert any(item.section == "prices" and "partial" in " ".join(item.warnings) for item in partial.data_coverage)
    assert any(item.section == "fundamentals" and "stale" in " ".join(item.warnings) for item in stale.data_coverage)
    assert any(risk.category == FindingCategory.DATA_QUALITY.value for risk in partial.risks)


def test_estimate_unsupported_missing_and_not_requested_remain_distinct():
    data = equity_growth_case()
    unsupported = EstimatesData(data.asset, Availability.NOT_SUPPORTED, None, FreshnessStatus.UNKNOWN, DataQuality(QualityStatus.PARTIAL, Availability.NOT_SUPPORTED))
    unavailable = _build(replace(data, estimates=unsupported, failures=(SectionFailure("earnings", "provider_error", "provider unavailable"),)))
    coverage = {item.section: item for item in unavailable.data_coverage}

    assert coverage["estimates"].availability is Availability.NOT_SUPPORTED
    assert coverage["earnings"].availability is Availability.UPSTREAM_ERROR
    assert coverage["profile"].availability is Availability.NOT_REQUESTED


def test_report_exposes_company_news_without_interpreting_headlines():
    data = equity_growth_case()
    news = CompanyNews(
        data.asset,
        (NewsArticle(NOW, "NVIDIA publishes quarterly results", "Evidence only", "https://example.com/nvda"),),
        ResearchProvenance("yfinance", "company_news", NOW),
        NOW,
        FreshnessStatus.FRESH,
        DataQuality(QualityStatus.COMPLETE),
    )

    report = _build(replace(data, news=news))

    assert report.news == news.articles
    assert next(item for item in report.data_coverage if item.section == "news").availability is Availability.AVAILABLE
    assert any(source.source_category == "company_news" and source.provider == "yfinance" for source in report.sources)


def test_report_exposes_observed_estimate_metrics_without_recommendation():
    data = equity_growth_case()
    estimates = EstimatesData(
        data.asset,
        Availability.AVAILABLE,
        ResearchProvenance("yfinance", "estimates_consensus", NOW),
        FreshnessStatus.FRESH,
        DataQuality(QualityStatus.COMPLETE),
        (("target_consensus", Decimal("210")), ("number_of_analysts", Decimal("42"))),
    )

    report = _build(replace(data, estimates=estimates))
    section = next(item for item in report.sections if item.key == "estimates")

    assert {item.key: item.value for item in section.metrics} == {
        "number_of_analysts": Decimal("42"), "target_consensus": Decimal("210"),
    }
    assert all("recommendation" not in item.key for item in section.metrics)


def test_report_carries_provider_earnings_observations_for_presentation():
    data = equity_growth_case()
    observation = EarningsObservation(
        earnings_date=NOW,
        period_end=None,
        reported_eps=None,
        estimated_eps=Decimal("1.25"),
        reported_revenue=None,
        estimated_revenue=Decimal("54000000000"),
        surprise=None,
        status="scheduled",
    )
    earnings = EarningsData(
        data.asset,
        (observation,),
        ResearchProvenance("fmp", "earnings_calendar", NOW),
        NOW,
        FreshnessStatus.FRESH,
        DataQuality(QualityStatus.COMPLETE),
    )

    report = _build(replace(data, earnings=earnings))

    assert report.earnings == (observation,)


def test_scheduled_earnings_date_does_not_advance_report_as_of():
    data = equity_growth_case()
    baseline_as_of = _build(data).as_of
    earnings = EarningsData(
        data.asset,
        (EarningsObservation(NOW + timedelta(days=7), None, None, Decimal("1.25"), None, None, None, "scheduled"),),
        ResearchProvenance("fmp", "earnings_calendar", NOW),
        NOW + timedelta(days=7),
        FreshnessStatus.FRESH,
        DataQuality(QualityStatus.COMPLETE),
    )

    report = _build(replace(data, earnings=earnings))

    assert report.as_of == baseline_as_of


def test_report_carries_bounded_price_points_for_ui_charting():
    report = _build(equity_growth_case())

    assert report.price_history
    assert report.price_history[-1].timestamp == equity_growth_case().prices.bars[-1].timestamp
    assert report.price_history[-1].close == equity_growth_case().prices.bars[-1].close
    assert len(report.price_history) <= 180


def test_report_samples_more_than_180_closes_uniformly_across_the_full_history():
    data = equity_growth_case()
    closes = tuple(Decimal(value) for value in """
        101 102 103 104 105 106 107 108 109 110 111 112
        113 114 115 116 117 118 119 120 121 122 123 124
        125 126 127 128 129 130 131 132 133 134 135 136
        137 138 139 140 141 142 143 144 145 146 147 148
        149 150 151 152 153 154 155 156 157 158 159 160
        161 162 163 164 165 166 167 168 169 170 171 172
        173 174 175 176 177 178 179 180 181 182 183 184
        185 186 187 188 189 190 191 192 193 194 195 196
        197 198 199 200 201 202 203 204 205 206 207 208
        209 210 211 212 213 214 215 216 217 218 219 220
        221 222 223 224 225 226 227 228 229 230 231 232
        233 234 235 236 237 238 239 240 241 242 243 244
        245 246 247 248 249 250 251 252 253 254 255 256
        257 258 259 260 261 262 263 264 265 266 267 268
        269 270 271 272 273 274 275 276 277 278 279 280
        281
    """.split())
    bars = tuple(
        PriceBar(NOW - timedelta(days=180 - index), None, None, None, close)
        for index, close in enumerate(closes)
    )
    data = replace(data, prices=replace(data.prices, bars=bars))

    first = _build(data)
    repeated = _build(data)
    expected_bars = bars[:179] + bars[180:]
    points = tuple((point.timestamp, point.close) for point in first.price_history)

    assert len(first.price_history) == 180
    assert points == tuple((bar.timestamp, bar.close) for bar in expected_bars)
    assert first.price_history_total == 181
    assert points[0] == (bars[0].timestamp, Decimal("101"))
    assert points[-1] == (bars[-1].timestamp, Decimal("281"))
    assert first.price_history == repeated.price_history


def test_report_retains_all_valid_closes_at_or_below_the_sampling_limit():
    data = equity_growth_case()
    bars = (
        PriceBar(NOW, None, None, None, Decimal("0")),
        PriceBar(NOW + timedelta(minutes=1), None, None, None, Decimal("13.25")),
        PriceBar(NOW + timedelta(minutes=2), None, None, None, None),
        PriceBar(NOW + timedelta(minutes=3), None, None, None, Decimal("21.75")),
    )
    report = _build(replace(data, prices=replace(data.prices, bars=bars)))

    assert tuple((point.timestamp, point.close) for point in report.price_history) == (
        (bars[0].timestamp, Decimal("0")),
        (bars[1].timestamp, Decimal("13.25")),
        (bars[3].timestamp, Decimal("21.75")),
    )
    assert report.price_history_total == 3


def test_report_distinguishes_empty_price_history_from_missing_prices():
    data = equity_growth_case()
    empty = _build(replace(data, prices=replace(data.prices, bars=())))
    missing = _build(replace(data, prices=None))

    assert empty.price_history == ()
    assert empty.price_history_total == 0
    assert missing.price_history == ()
    assert missing.price_history_total is None


def test_report_preserves_flat_price_history():
    data = equity_growth_case()
    bars = tuple(
        PriceBar(NOW + timedelta(minutes=index), None, None, None, Decimal("4.2"))
        for index in range(180)
    )
    report = _build(replace(data, prices=replace(data.prices, bars=bars)))

    assert len(report.price_history) == 180
    assert tuple(point.timestamp for point in report.price_history) == tuple(bar.timestamp for bar in bars)
    assert all(point.close == Decimal("4.2") for point in report.price_history)
    assert report.price_history_total == 180


def test_report_exposes_quote_filings_attempts_and_stable_failure_codes():
    data = equity_growth_case()
    attempts = (
        ProviderAttempt("yfinance", "failure", "no_data"),
        ProviderAttempt("fmp", "success", None),
    )
    quote_provenance = ResearchProvenance("fmp", "equity_quote", NOW, attempts=attempts)
    quote = EquityQuote(
        data.asset, Decimal("216.61"), Decimal("214.40"), None, None, None,
        None, Decimal("225"), Decimal("86"), None, None, "USD",
        quote_provenance, NOW, FreshnessStatus.FRESH,
        DataQuality(QualityStatus.COMPLETE),
    )
    filings = CompanyFilings(
        data.asset,
        (CompanyFiling(
            "10-Q", NOW, NOW, "Quarterly report", "fixture-accession",
            "https://www.sec.gov/Archives/example.htm",
        ),),
        ResearchProvenance("sec", "company_filings", NOW),
        NOW,
        FreshnessStatus.FRESH,
        DataQuality(QualityStatus.COMPLETE),
    )
    report = _build(replace(
        data,
        quote=quote,
        filings=filings,
        failures=(SectionFailure("earnings", "entitlement_required", "Safe tier limitation", "fmp"),),
    ))

    snapshot = next(section for section in report.sections if section.key == "snapshot")
    assert {item.key: item.value for item in snapshot.metrics}["last_price"] == Decimal("216.61")
    assert report.filings[0].form_type == "10-Q"
    assert next(source for source in report.sources if source.source_category == "equity_quote").attempts == attempts
    earnings = next(item for item in report.data_coverage if item.section == "earnings")
    assert earnings.failures[0].code == "entitlement_required"


def test_crypto_report_does_not_fabricate_derivatives_and_uses_crypto_sections_only():
    report = _build(crypto_price_volume_case())
    keys = [section.key for section in report.sections]

    assert "price_trend" in keys
    assert "growth" not in keys and "balance_sheet" not in keys
    derivatives = next(item for item in report.data_coverage if item.section == "derivatives_metadata")
    assert derivatives.availability is Availability.NOT_SUPPORTED
    assert not any("derivatives" in metric.key for section in report.sections for metric in section.metrics)


def test_etf_report_uses_basic_etf_template_without_holdings_decomposition():
    source = equity_growth_case()
    asset = AssetIdentity("SPY", CanonicalAssetType.ETF, currency="USD")
    data = AssetResearchData(asset, prices=replace(source.prices, asset=asset), quality=DataQuality(QualityStatus.COMPLETE))
    report = _build(data)
    keys = [section.key for section in report.sections]

    assert "market_behavior" in keys
    assert "growth" not in keys and "fund_market_characteristics" not in keys
    assert all("holding" not in metric.key for section in report.sections for metric in section.metrics)


def test_positive_negative_and_mixed_factors_are_finding_backed():
    report = _build(equity_growth_case())
    known = {item.id for item in ResearchRelevanceEngine().analyze(equity_growth_case()).findings}

    assert report.positive_factors
    assert report.mixed_factors
    assert all(item.finding_id in known for group in (report.positive_factors, report.negative_factors, report.mixed_factors) for item in group)
    assert all(risk.finding_id in known for risk in report.risks if risk.finding_id is not None)


def test_report_rejects_analysis_for_another_asset():
    data = equity_growth_case()
    other = crypto_price_volume_case()
    with pytest.raises(ValueError, match="same canonical asset"):
        AssetResearchReportService().build_asset_report(research_data=data, analysis=ResearchRelevanceEngine().analyze(other))


def test_report_is_deterministic_and_json_compatible_without_gemini():
    data = equity_growth_case()
    first = _build(data, ReportDepth.DETAILED)
    second = _build(data, ReportDepth.DETAILED)

    assert canonical_json(first) == canonical_json(second)
    payload = to_jsonable(first)
    assert payload["generated_at"] == NOW.isoformat()
    assert "gemini" not in canonical_json(first).lower()
