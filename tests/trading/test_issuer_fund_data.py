from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from html import escape
from io import BytesIO
import json
import zipfile

import pytest

from app.trading.research import ResearchData
from app.trading.research import issuer_fund_data as source


def _input(element_id: str, value: object) -> str:
    return f'<input id="{element_id}" value="{escape(json.dumps(value), quote=True)}">'


def _page(
    *, ticker: str = "SPY", isin: str = "US78462F1030", include_dates: bool = True,
    include_yield_date: bool = True,
) -> str:
    quick = {
        "attrs": {
            "fund-ticker": {"value": ticker},
            "isin": {"value": isin},
            "fund-name": {"value": "Example SPDR Fund"},
            "investment-geography": {"value": "United States"},
            "expense-ratio": {"originalValue": "0.0945"},
            "inception-date": {"originalValue": "22-Jan-1993"},
            "aum": {"originalValue": "123456789.25", "asOfDate": "as of Oct 22 2026"},
            "nav": {"originalValue": "123.45", "asOfDate": "as of Oct 22 2026"},
        }
    }
    sectors = {
        "asOfDate": "as of Oct 22 2026",
        "attrArray": [
            {"name": {"value": "Information Technology"}, "weight": {"originalValue": "37.5"}},
            {"name": {"value": "Financials"}, "weight": {"value": "12.25%"}},
        ],
    }
    date = "<span class='date'>as of Oct 25 2026</span>" if include_dates else ""
    return f"""
      {_input('fund-quick-info', quick)}
      {_input('fund-sector-breakdown', sectors)}
      <section><h2 class='comp-title'>Key Features</h2>
        <ul><li>The Example SPDR Fund seeks to provide investment results that correspond to its benchmark.</li></ul>
      </section>
      <section><h2 class='comp-title'>Fund Information {date}</h2>
        <table><tbody>
          <tr><th class='label'>Benchmark</th><td class='data'>Example 500 Index</td></tr>
          <tr><th class='label'>Base Currency</th><td class='data'>USD</td></tr>
          <tr><th class='label'>Sponsor</th><td class='data'>Example Sponsor</td></tr>
          <tr><th class='label'>Trustee</th><td class='data'>Example Trustee</td></tr>
          <tr><th class='label'>Distribution Frequency</th><td class='data'>Quarterly</td></tr>
        </tbody></table>
      </section>
      <section><h2 class='comp-title'>Yields {'as of Oct 22 2026' if include_yield_date else ''}</h2>
        <table><tbody>
          <tr><th>Fund Distribution Yield Fund Distribution Yield The sum of distributions over the trailing 365 days divided by NAV.</th><td>0.99%</td></tr>
          <tr><th>Index Dividend Yield Index Dividend Yield The weighted average of underlying indicated dividends.</th><td>1.10%</td></tr>
        </tbody></table>
      </section>
      <section><h2 class='comp-title'>Listing Information</h2>
        <table><thead><tr><th>Exchange</th><th>Trading Currency</th><th>Ticker</th></tr></thead>
          <tbody><tr><td>NYSE ARCA</td><td>USD</td><td>SPY</td></tr></tbody></table>
      </section>
    """


def _xlsx(*, ticker: str = "SPY", include_date: bool = True, include_cash: bool = False, cash_ticker: str = "") -> bytes:
    strings = [
        "Fund Name:", "Example SPDR Fund", "Ticker Symbol:", ticker,
        "Holdings:", "As of 22-Oct-2026", "Name", "Ticker", "Identifier",
        "SEDOL", "Weight", "Sector", "Shares Held", "Local Currency",
        "NVIDIA CORP", "NVDA", "67066G104", "2379504", "-", "USD",
        "APPLE INC", "AAPL", "037833100", "2046251",
        "CASH AND CASH EQUIVALENTS", "", "Cash",
    ]
    index = {value: position for position, value in enumerate(strings)}
    if not include_date:
        strings[index["As of 22-Oct-2026"]] = ""

    def shared_cell(ref: str, value: str) -> str:
        return f'<c r="{ref}" t="s"><v>{index[value]}</v></c>'

    def number_cell(ref: str, value: str) -> str:
        return f'<c r="{ref}"><v>{value}</v></c>'

    rows = [
        f'<row r="1">{shared_cell("A1", "Fund Name:")}{shared_cell("B1", "Example SPDR Fund")}</row>',
        f'<row r="2">{shared_cell("A2", "Ticker Symbol:")}{shared_cell("B2", ticker)}</row>',
        f'<row r="3">{shared_cell("A3", "Holdings:")}{shared_cell("B3", "As of 22-Oct-2026") if include_date else ""}</row>',
        f'<row r="5">{shared_cell("A5", "Name")}{shared_cell("B5", "Ticker")}{shared_cell("C5", "Identifier")}{shared_cell("D5", "SEDOL")}{shared_cell("E5", "Weight")}{shared_cell("F5", "Sector")}{shared_cell("G5", "Shares Held")}{shared_cell("H5", "Local Currency")}</row>',
        f'<row r="6">{shared_cell("A6", "NVIDIA CORP")}{shared_cell("B6", "NVDA")}{shared_cell("C6", "67066G104")}{shared_cell("D6", "2379504")}{number_cell("E6", "7.5")}{shared_cell("F6", "-")}{number_cell("G6", "10")}{shared_cell("H6", "USD")}</row>',
        f'<row r="7">{shared_cell("A7", "APPLE INC")}{shared_cell("B7", "AAPL")}{shared_cell("C7", "037833100")}{shared_cell("D7", "2046251")}{number_cell("E7", "6.25")}{shared_cell("F7", "-")}{number_cell("G7", "20")}{shared_cell("H7", "USD")}</row>',
    ]
    if include_cash:
        rows.append(
            f'<row r="8">{shared_cell("A8", "CASH AND CASH EQUIVALENTS")}{shared_cell("B8", cash_ticker)}'
            f'{number_cell("E8", "0.5")}{shared_cell("F8", "Cash")}{number_cell("G8", "100")}{shared_cell("H8", "USD")}</row>'
        )
    strings_xml = "".join(f"<si><t>{escape(value)}</t></si>" for value in strings)
    sheet_xml = "<worksheet xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'><sheetData>" + "".join(rows) + "</sheetData></worksheet>"
    workbook_xml = "<workbook xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main' xmlns:r='http://schemas.openxmlformats.org/officeDocument/2006/relationships'><sheets><sheet name='holdings' sheetId='1' r:id='rId1'/></sheets></workbook>"
    rels_xml = "<Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'><Relationship Id='rId1' Target='worksheets/sheet1.xml' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet'/></Relationships>"
    contents = BytesIO()
    with zipfile.ZipFile(contents, "w") as archive:
        archive.writestr("xl/workbook.xml", workbook_xml)
        archive.writestr("xl/_rels/workbook.xml.rels", rels_xml)
        archive.writestr("xl/sharedStrings.xml", f"<sst xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'>{strings_xml}</sst>")
        archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)
    return contents.getvalue()


def test_page_parser_keeps_official_labels_and_each_observation_date_separate():
    row = source._parse_page(_page(), symbol="SPY", expected_isin="US78462F1030")

    assert row["benchmark"] == "Example 500 Index"
    assert row["name"] == row["fund_name"] == "Example SPDR Fund"
    assert row["objective"] == "The Example SPDR Fund seeks to provide investment results that correspond to its benchmark."
    assert row["distribution_frequency"] == "Quarterly"
    assert row["base_currency"] == row["currency"] == "USD"
    assert row["exchange"] == "NYSE ARCA"
    assert row["expense_ratio"] == Decimal("0.000945")
    assert row["inception_date"] == "1993-01-22"
    assert row["website"] == row["source_url"]
    assert row["assets_under_management_currency"] == row["nav_currency"] == "USD"
    assert row["assets_under_management"] == Decimal("123456789.25")
    assert row["nav"] == Decimal("123.45")
    assert row["assets_under_management_as_of"] == row["nav_as_of"] == "2026-10-22"
    assert row["distribution_yield"] == Decimal("0.0099")
    assert row["distribution_yield_as_of"] == "2026-10-22"
    assert row["as_of"] == "2026-10-25"
    assert row["sectors"] == {
        "Information Technology": Decimal("0.375"),
        "Financials": Decimal("0.1225"),
    }
    assert row["sectors_as_of"] == "2026-10-22"
    assert row["sponsor"] == "Example Sponsor"
    assert row["trustee"] == "Example Trustee"
    assert "issuer" not in row
    assert "replication_method" not in row


def test_holdings_parser_returns_full_rows_with_fraction_weights_and_date():
    holdings, as_of = source._parse_holdings(_xlsx(), symbol="SPY")

    assert as_of == "2026-10-22"
    assert holdings == [
        {"weight": Decimal("0.075"), "symbol": "NVDA", "name": "NVIDIA CORP", "identifier": "67066G104", "sedol": "2379504", "shares_held": Decimal("10"), "local_currency": "USD"},
        {"weight": Decimal("0.0625"), "symbol": "AAPL", "name": "APPLE INC", "identifier": "037833100", "sedol": "2046251", "shares_held": Decimal("20"), "local_currency": "USD"},
    ]


def test_page_and_holdings_identity_mismatches_are_rejected():
    with pytest.raises(ValueError, match="identity"):
        source._parse_page(_page(ticker="QQQ"), symbol="SPY", expected_isin="US78462F1030")
    with pytest.raises(ValueError, match="identity"):
        source._parse_page(_page(isin="US0000000000"), symbol="SPY", expected_isin="US78462F1030")
    with pytest.raises(ValueError, match="identity"):
        source._parse_holdings(_xlsx(ticker="QQQ"), symbol="SPY")


@pytest.mark.parametrize("cash_ticker", ["", "-"])
def test_cash_weight_row_is_preserved_even_when_it_has_no_ticker_symbol(cash_ticker):
    holdings, _ = source._parse_holdings(_xlsx(include_cash=True, cash_ticker=cash_ticker), symbol="SPY")

    assert holdings[-1] == {
        "weight": Decimal("0.005"), "name": "CASH AND CASH EQUIVALENTS",
        "sector": "Cash", "shares_held": Decimal("100"), "local_currency": "USD",
    }


def test_missing_required_observation_dates_are_rejected():
    with pytest.raises(ValueError, match="date"):
        source._parse_page(_page(include_dates=False), symbol="SPY", expected_isin="US78462F1030")
    with pytest.raises(ValueError, match="distribution yield observation date"):
        source._parse_page(_page(include_yield_date=False), symbol="SPY", expected_isin="US78462F1030")
    with pytest.raises(ValueError, match="date"):
        source._parse_holdings(_xlsx(include_date=False), symbol="SPY")


def test_fetch_returns_research_data_and_unsupported_symbols_do_not_fetch(monkeypatch):
    def fake_download(url, *, max_bytes):
        del max_bytes
        return _page().encode() if url == source._PAGE_URL else _xlsx()

    monkeypatch.setattr(source, "_bounded_download", fake_download)

    result = source.fetch_issuer_fund_data(" spy ")

    assert isinstance(result, ResearchData)
    assert result.symbol == "SPY"
    assert result.asset_type == "etf"
    assert result.category == "issuer_fund_data"
    assert result.provider == "ssga"
    assert result.data[0]["benchmark"] == "Example 500 Index"
    assert result.data[0]["holdings"][0]["weight"] == "0.075"
    assert result.data[0]["holdings_as_of"] == "2026-10-22"
    assert result.data[0]["source_url"].startswith("https://www.ssga.com/")
    assert result.data[0]["holdings_url"].startswith("https://www.ssga.com/")
    assert result.retrieved_at.tzinfo == timezone.utc

    def unexpected_fetch(_symbol):
        pytest.fail("unsupported symbols must not make issuer requests")

    monkeypatch.setattr(source, "_download_official_data", unexpected_fetch)
    assert source.fetch_issuer_fund_data("QQQ") is None
