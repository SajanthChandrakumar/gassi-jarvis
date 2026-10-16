"""Offline checks of the official Swiss series through OpenBB and canonical data."""

from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.trading.research.openbb_client import (
    OpenBBResearchClient, ResearchNoDataError, ResearchProviderError,
    ResearchUnsupportedEndpointError,
)
from app.trading.research.service import CanonicalResearchService


def csv_response(cube, dimensions, rows, published="2026-09-21 09:00"):
    return '\ufeff"CubeId";"' + cube + '"\n"PublishingDate";"' + published + '"\n\n' + \
        '"Date";' + ';'.join('"' + name + '"' for name in dimensions) + ';"Value"\n' + rows


def install_response(monkeypatch, body, status=200):
    from app.trading.research import snb_macro
    calls = []

    def request(url, **kwargs):
        calls.append((url, kwargs))
        return SimpleNamespace(text=body, status_code=status, raise_for_status=lambda: None)

    monkeypatch.setattr(snb_macro, "make_request", request)
    return calls


def get_series(indicator, **kwargs):
    return CanonicalResearchService(OpenBBResearchClient()).get_macro_series(
        indicator, provider="snb", country="switzerland",
        start_date=date(2026, 1, 1), end_date=date(2026, 9, 30), **kwargs,
    )


@pytest.mark.parametrize("indicator,cube,dimensions,row,expected,unit,period,frequency", [
    ("inflation", "plkopr", ("D0",), '"2026-08";"VVP";"0.81"\n', "0.81", "% YoY", "2026-08", "month"),
    ("unemployment", "amarbma", ("D0",), '"2026-08";"T1";"2.9"\n', "2.9", "%", "2026-08", "month"),
    ("policy_rate", "snbgwdzid", ("D0",), '"2026-09-25";"LZ";"0"\n', "0", "%", "2026-09-25", "day"),
    ("treasury_10y", "rendeiduebm", ("D0", "D1"), '"2026-08";"CHF";"10J";"-0.05"\n', "-0.05", "%", "2026-08", "month"),
    ("real_gdp_growth", "gdprpq", ("D0", "D1"), '"2026-Q2";"VVK";"BBIPS";"0.2"\n', "0.2", "% QoQ", "2026-Q2", "quarter"),
])
def test_official_series_preserve_definition_period_and_publication(
    monkeypatch, indicator, cube, dimensions, row, expected, unit, period, frequency,
):
    calls = install_response(monkeypatch, csv_response(cube, dimensions, row))
    series = get_series(indicator)
    assert series.observations[-1].value == Decimal(expected)
    assert series.observations[-1].period == period
    assert series.unit == unit
    assert series.frequency == frequency
    assert series.provenance.provider == "snb"
    assert series.asset.country == "switzerland"
    assert series.definition
    assert series.source_name in {"BFS via SNB", "SECO via SNB", "SNB"}
    assert series.source_url.startswith("https://data.snb.ch/en/topics/")
    assert series.published_at == datetime(2026, 9, 21, 7, tzinfo=timezone.utc)
    assert dict(series.provenance.request_parameters)["cube"] == cube
    url, params = calls[0]
    assert url == f"https://data.snb.ch/api/cube/{cube}/data/csv/en"
    assert params["params"]["fromDate"] == "2026-01-01"
    assert params["params"]["toDate"] == "2026-09-30"
    assert params["allow_redirects"] is False
    if frequency == "month":
        assert series.as_of.date() == date(2026, 8, 31)
    if frequency == "quarter":
        assert series.as_of.date() == date(2026, 6, 30)


def test_filter_dimensions_and_scope_and_keep_missing_not_zero(monkeypatch):
    rows = (
        '"2026-07";"T1";"2.8"\n'
        '"2026-08";"T1";""\n'
        '"2026-08";"S1";"3.0"\n'
        '"2026-08";"T0";"100000"\n'
        '"2025-12";"T1";"9"\n'
        '"2026-10";"T1";"9"\n'
    )
    install_response(monkeypatch, csv_response("amarbma", ("D0",), rows))
    series = get_series("unemployment")
    assert [(row.period, row.value) for row in series.observations] == [("2026-07", Decimal("2.8"))]
    assert series.as_of.date() == date(2026, 7, 31)


@pytest.mark.parametrize("value", ["NaN", "Infinity", "not-a-number"])
def test_invalid_numeric_data_is_unavailable_not_a_value(monkeypatch, value):
    install_response(monkeypatch, csv_response("snbgwdzid", ("D0",), f'"2026-09-25";"LZ";"{value}"\n'))
    with pytest.raises(ResearchProviderError) as error:
        get_series("policy_rate")
    assert error.value.provider == "snb"


@pytest.mark.parametrize("body", [
    csv_response("wrong_cube", ("D0",), '"2026-08";"VVP";"0.8"\n'),
    csv_response("plkopr", ("D1",), '"2026-08";"VVP";"0.8"\n'),
    csv_response("plkopr", ("D0",), '"2026-08";"VVP";"0.8"\n', published="unknown"),
    csv_response("plkopr", ("D0",), '"2026-08";"VVP";"0.8"\n"2026-08";"VVP";"0.9"\n'),
    "<html>Maintenance</html>",
    csv_response("plkopr", ("D0",), '"2026-08";"VVP";"0.8'),
    '"CubeId";"wrong_cube"\n' + csv_response("plkopr", ("D0",), '"2026-08";"VVP";"0.8"\n').lstrip('\ufeff'),
    '"PublishingDate";"2026-08-21 09:00"\n' + csv_response("plkopr", ("D0",), '"2026-08";"VVP";"0.8"\n').lstrip('\ufeff'),
])
def test_reject_ambiguous_or_malformed_provider_response(monkeypatch, body):
    install_response(monkeypatch, body)
    with pytest.raises(ResearchProviderError):
        get_series("inflation")


def test_gdp_does_not_select_level_or_unsports_adjusted_series(monkeypatch):
    install_response(monkeypatch, csv_response("gdprpq", ("D0", "D1"),
        '"2026-Q2";"WMF";"BBIPS";"200000"\n'
        '"2026-Q2";"VVK";"BBIP";"1.2"\n'
        '"2026-Q2";"VVK";"BBIPS";"0.2"\n'))
    series = get_series("real_gdp_growth")
    assert series.observations[0].value == Decimal("0.2")
    assert "sports" in series.definition


def test_no_matching_data_has_no_proxy_fallback(monkeypatch):
    install_response(monkeypatch, csv_response("amarbma", ("D0",), '"2026-08";"S1";"3"\n'))
    with pytest.raises(ResearchNoDataError):
        get_series("unemployment")


@pytest.mark.parametrize("kwargs", [{"transform": "pc1"}, {"unit": "% YoY"}, {"series_id": "IRSTCI01CHM156N"}])
def test_refuse_proxy_or_mislabeled_policy_rate(monkeypatch, kwargs):
    calls = install_response(monkeypatch, "")
    with pytest.raises(ResearchUnsupportedEndpointError):
        get_series("policy_rate", **kwargs)
    assert calls == []


def test_fetcher_rejects_unbounded_or_foreign_queries():
    from app.trading.research.snb_macro import SnbMacroFetcher
    for params in (
        {"symbol": "unknown", "country": "switzerland"},
        {"symbol": "inflation", "country": "united_states"},
        {"symbol": "inflation", "country": "switzerland", "start_date": "2000-01-01", "end_date": "2026-09-30"},
        {"symbol": "inflation", "country": "switzerland", "start_date": "2026-09-30", "end_date": "2026-01-01"},
    ):
        with pytest.raises(ValueError):
            SnbMacroFetcher.transform_query(params)
