from datetime import timedelta
from decimal import Decimal

from app.trading.research.historical import HistoricalEvent, HistoricalStatus
from app.trading.research.historical_service import HistoricalResearchPolicy, HistoricalResearchService
from app.trading.research.serialization import canonical_json
from tests.trading.test_statistical_research import _prices


SERVICE = HistoricalResearchService(HistoricalResearchPolicy(minimum_events=2, minimum_volatility_lookback=3))


def test_forward_event_study_uses_only_complete_future_windows():
    prices = _prices("BTC", [0.10, 0.10, -0.10, 0.20, 0.10])
    first = prices.bars[1].timestamp
    last = prices.bars[-1].timestamp
    result = SERVICE.event_study(prices, (HistoricalEvent(first), HistoricalEvent(last)), horizons=(1, 3))

    assert result.status is HistoricalStatus.COMPLETE
    assert [(item.event_timestamp, item.horizon) for item in result.forward_returns] == [(first, 1), (first, 3)]
    assert result.summaries[0].mean == Decimal("0.1")


def test_threshold_events_and_no_event_case_are_deterministic():
    prices = _prices("BTC", [0.01, 0.10, -0.02, 0.12, 0.01])
    events = SERVICE.return_threshold_events(prices, threshold=Decimal("0.08"))
    no_events = SERVICE.event_study(prices, (), horizons=(1,))

    assert len(events) == 2
    assert no_events.status is HistoricalStatus.INSUFFICIENT_DATA
    assert any("No events" in warning for warning in no_events.warnings)


def test_volatility_events_use_only_information_available_at_event_time():
    prices = _prices("BTC", [0.01, -0.01, 0.01, -0.01, 0.20, -0.20, 0.01, -0.01])
    events = SERVICE.volatility_percentile_events(prices, lookback=3, percentile=Decimal("0.5"))

    assert events
    assert all(event.timestamp <= prices.bars[-1].timestamp for event in events)


def test_vectorbt_drawdowns_are_normalized_into_canonical_episodes():
    prices = _prices("NVDA", [0.10, -0.10, -0.10, 0.30, 0.10])
    result = SERVICE.drawdown_analysis(prices)

    assert result.status is HistoricalStatus.COMPLETE
    assert result.maximum_drawdown == Decimal("-0.19")
    assert result.episodes[0].recovered is True
    assert result.episodes[0].recovery_at is not None


def test_regime_results_construct_samples_without_reimplementing_statistics():
    prices = _prices("NVDA", [0.05, -0.05, 0.05, -0.05, 0.05, -0.05])
    first = (prices.bars[1].timestamp, prices.bars[2].timestamp)
    second = (prices.bars[3].timestamp, prices.bars[4].timestamp)
    result = SERVICE.regime_comparison(prices, first, second, horizons=(1,), first_label="up", second_label="down")

    assert result.status is HistoricalStatus.COMPLETE
    assert result.first_event_study.context.parameters[-1] == ("label", "up")
    assert canonical_json(result) == canonical_json(SERVICE.regime_comparison(prices, first, second, horizons=(1,), first_label="up", second_label="down"))
