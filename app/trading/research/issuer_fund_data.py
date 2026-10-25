"""Bounded official State Street issuer data for the supported SPY fund.

The installed OpenBB/Yahoo ETF profile route omits several issuer-published
fund fields. This narrowly scoped Fetcher reads the public State Street SPY
page and its linked daily holdings workbook; it never accepts a remote URL
from a caller and returns only values explicitly present in those sources.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from io import BytesIO
import json
import posixpath
import re
import time
from typing import Any
from urllib.parse import urlparse
from zipfile import BadZipFile, ZipFile
import xml.etree.ElementTree as ET

from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.fetcher import Fetcher, run_async
from openbb_core.provider.abstract.query_params import QueryParams
from pydantic import Field

from .canonical import ProviderAttempt
from .openbb_client import ResearchData, ResearchProviderError
from .yahoo_supplement import _bounded_yahoo_session


_PROVIDER = "ssga"
_SYMBOL = "SPY"
_ISIN = "US78462F1030"
_PAGE_URL = "https://www.ssga.com/us/en/intermediary/etfs/state-street-spdr-sp-500-etf-trust-spy"
_HOLDINGS_URL = "https://www.ssga.com/library-content/products/fund-data/etfs/us/holdings-daily-us-en-spy.xlsx"
_PAGE_MAX_BYTES = 8 * 1024 * 1024
_HOLDINGS_MAX_BYTES = 16 * 1024 * 1024
_XLSX_MAX_UNCOMPRESSED_BYTES = 64 * 1024 * 1024
_FETCH_TIMEOUT_SECONDS = 10


class IssuerFundDataQuery(QueryParams):
    symbol: str = Field(min_length=1, max_length=16)


class IssuerFundData(Data):
    """Typed OpenBB result row; nested source tables remain JSON-shaped."""

    symbol: str
    name: str | None = None
    fund_name: str | None = None
    isin: str | None = None
    website: str | None = None
    exchange: str | None = None
    expense_ratio: Decimal | None = None
    inception_date: str | None = None
    investment_geography: str | None = None
    benchmark: str | None = None
    distribution_frequency: str | None = None
    distribution_yield: Decimal | None = None
    distribution_yield_as_of: str | None = None
    base_currency: str | None = None
    currency: str | None = None
    sponsor: str | None = None
    trustee: str | None = None
    assets_under_management: Decimal | None = None
    assets_under_management_currency: str | None = None
    assets_under_management_as_of: str | None = None
    nav: Decimal | None = None
    nav_currency: str | None = None
    nav_as_of: str | None = None
    objective: str | None = None
    as_of: str
    source_url: str
    holdings: list[dict[str, Any]]
    holdings_as_of: str
    holdings_complete: bool
    sectors: dict[str, Any] = Field(default_factory=dict)
    sectors_as_of: str | None = None
    holdings_url: str


class IssuerFundDataFetcher(Fetcher[IssuerFundDataQuery, IssuerFundData]):
    require_credentials = False

    @staticmethod
    def transform_query(params: dict[str, Any]) -> IssuerFundDataQuery:
        return IssuerFundDataQuery(**params)

    @staticmethod
    async def aextract_data(
        query: IssuerFundDataQuery,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        del credentials, kwargs
        # The page and workbook are separate fixed requests, each with a
        # bounded ten-second socket timeout.
        return await asyncio.wait_for(
            asyncio.to_thread(_download_official_data, query.symbol),
            timeout=2 * _FETCH_TIMEOUT_SECONDS + 2,
        )

    @staticmethod
    def transform_data(
        query: IssuerFundDataQuery,
        data: dict[str, Any],
        **kwargs: Any,
    ) -> IssuerFundData:
        del query, kwargs
        return IssuerFundData.model_validate(data)


def supports_issuer_fund_data(symbol: str) -> bool:
    """Return whether a symbol is covered by this fixed issuer adapter."""
    return isinstance(symbol, str) and symbol.strip().upper() == _SYMBOL


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    result = " ".join(value.split()).strip()
    return result or None


def _iso_date(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if cleaned.lower().startswith("as of "):
        cleaned = cleaned[6:].strip()
    for pattern in ("%b %d %Y", "%d-%b-%Y", "%Y-%m-%d", "%b %d, %Y"):
        try:
            return datetime.strptime(cleaned, pattern).date().isoformat()
        except ValueError:
            continue
    try:
        return date.fromisoformat(cleaned[:10]).isoformat()
    except ValueError:
        return None


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip().replace(",", "")
    if text.endswith("%"):
        text = text[:-1].strip()
    if not text:
        return None
    try:
        parsed = Decimal(text)
    except (InvalidOperation, ValueError, TypeError):
        return None
    return parsed if parsed.is_finite() else None


def _required_decimal(value: Any, label: str) -> Decimal:
    parsed = _decimal(value)
    if parsed is None:
        raise ValueError(f"Invalid official {label} value")
    return parsed


def _nested_value(item: Any, key: str = "value") -> Any:
    if isinstance(item, dict):
        return item.get(key)
    return None


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.inputs: dict[str, str] = {}
        self.table_values: dict[str, str] = {}
        self.listing_values: dict[str, str] = {}
        self._listing_headers: list[str] | None = None
        self._row_cells: list[tuple[str, str]] | None = None
        self._cell_parts: list[str] | None = None
        self._cell_type: str | None = None
        self._heading: str | None = None
        self._heading_parts: list[str] = []
        self._headings: list[str] = []
        self._key_features = False
        self._feature_parts: list[str] | None = None
        self.features: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "input" and values.get("id") in {"fund-quick-info", "fund-sector-breakdown"}:
            value = values.get("value")
            if value:
                self.inputs[str(values["id"])] = value
        if tag == "tr":
            self._row_cells = []
        elif tag in {"th", "td"} and self._row_cells is not None:
            self._cell_type = tag
            self._cell_parts = []
        elif tag in {"h2", "h3"}:
            self._heading = tag
            self._heading_parts = []
        elif tag == "li" and self._key_features and self._feature_parts is None:
            self._feature_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"th", "td"} and self._cell_type == tag:
            text = _clean_text("".join(self._cell_parts or []))
            if text is not None and self._row_cells is not None:
                self._row_cells.append((tag, text))
            self._cell_parts = None
            self._cell_type = None
        elif tag == "tr" and self._row_cells is not None:
            cells = self._row_cells
            kinds = {kind for kind, _ in cells}
            if cells and kinds == {"th"}:
                headers = [value for _, value in cells]
                if any(value.casefold() == "trading currency" for value in headers):
                    self._listing_headers = headers
            elif cells and kinds == {"td"} and self._listing_headers:
                self.listing_values = {
                    header.casefold(): value
                    for header, (_, value) in zip(self._listing_headers, cells)
                }
                self._listing_headers = None
            else:
                label = next((value for kind, value in cells if kind == "th"), None)
                value = next((value for kind, value in cells if kind == "td"), None)
                if label and value:
                    self.table_values[label.casefold()] = value
            self._row_cells = None
        elif tag in {"h2", "h3"} and self._heading == tag:
            heading = _clean_text("".join(self._heading_parts))
            if heading:
                self._headings.append(heading)
                self._key_features = heading.casefold().startswith("key features")
            self._heading = None
        elif tag == "li" and self._feature_parts is not None:
            feature = _clean_text("".join(self._feature_parts))
            if feature:
                self.features.append(feature)
            self._feature_parts = None

    def handle_data(self, data: str) -> None:
        if self._cell_parts is not None:
            self._cell_parts.append(data)
        if self._heading:
            self._heading_parts.append(data)
        if self._feature_parts is not None:
            self._feature_parts.append(data)


def _date_from_heading(headings: list[str], title: str) -> str | None:
    for heading in headings:
        match = re.match(rf"^{re.escape(title)}\s+as of\s+(.+)$", heading, re.IGNORECASE)
        if match:
            return _iso_date(match.group(1))
    return None


def _parse_page(html: str, *, symbol: str, expected_isin: str) -> dict[str, Any]:
    parser = _PageParser()
    parser.feed(html)
    try:
        quick = json.loads(parser.inputs["fund-quick-info"])
    except (KeyError, json.JSONDecodeError, TypeError) as exc:
        raise ValueError("Official issuer page is missing fund identity metadata") from exc
    attrs = quick.get("attrs") if isinstance(quick, dict) else None
    if not isinstance(attrs, dict):
        raise ValueError("Official issuer page has invalid fund identity metadata")
    found_symbol = _nested_value(attrs.get("fund-ticker"))
    found_isin = _nested_value(attrs.get("isin"))
    if str(found_symbol or "").strip().upper() != symbol.upper() or str(found_isin or "").strip().upper() != expected_isin.upper():
        raise ValueError("Official issuer page fund identity mismatch")

    as_of = _date_from_heading(parser._headings, "Fund Information")
    if as_of is None:
        raise ValueError("Official issuer page is missing the Fund Information observation date")

    row: dict[str, Any] = {
        "symbol": symbol.upper(), "as_of": as_of, "source_url": _PAGE_URL,
        "website": _PAGE_URL,
    }
    fields = {
        "fund_name": ("fund-name", "value"),
        "isin": ("isin", "value"),
        "investment_geography": ("investment-geography", "value"),
    }
    for output, (source, key) in fields.items():
        text = _clean_text(_nested_value(attrs.get(source), key))
        if text:
            row[output] = text
            if output == "fund_name":
                row["name"] = text

    for label, output in (
        ("benchmark", "benchmark"),
        ("distribution frequency", "distribution_frequency"),
        ("base currency", "base_currency"),
        ("sponsor", "sponsor"),
        ("trustee", "trustee"),
    ):
        value = parser.table_values.get(label)
        if value:
            row[output] = value

    # SSGA labels the fund's own trailing-365-day, NAV-based metric
    # separately from the benchmark's dividend yield. Preserve the source
    # meaning and observation date rather than mapping it to a generic yield.
    distribution_yield = next(
        (
            value
            for label, value in parser.table_values.items()
            if label == "fund distribution yield"
            or label.startswith("fund distribution yield")
        ),
        None,
    )
    if distribution_yield is not None:
        observed_date = _date_from_heading(parser._headings, "Yields")
        if observed_date is None:
            raise ValueError("Official fund distribution yield observation date is missing")
        row["distribution_yield"] = _required_decimal(
            distribution_yield, "fund distribution yield"
        ) / Decimal("100")
        row["distribution_yield_as_of"] = observed_date
    row["currency"] = parser.listing_values.get("trading currency")
    row["exchange"] = parser.listing_values.get("exchange")

    # The official quick-info values are percentage points. Canonical ETF
    # profiles store expense ratios as fractions, as they do Yahoo netExpenseRatio.
    expense_info = attrs.get("expense-ratio") or attrs.get("gross-expense-ratio")
    if isinstance(expense_info, dict):
        expense_value = _decimal(expense_info.get("originalValue"))
        if expense_value is not None:
            row["expense_ratio"] = expense_value / Decimal("100")
    inception_info = attrs.get("inception-date")
    if isinstance(inception_info, dict):
        inception = _iso_date(inception_info.get("originalValue") or inception_info.get("value"))
        if inception:
            row["inception_date"] = inception

    # These are explicitly reported in the quick-info object in the fund's
    # stated base currency. Their values and dates remain distinct.
    for source, output, currency_key in (
        ("aum", "assets_under_management", "assets_under_management_currency"),
        ("nav", "nav", "nav_currency"),
    ):
        value_info = attrs.get(source)
        if not isinstance(value_info, dict):
            continue
        raw_value = value_info.get("originalValue")
        raw_date = value_info.get("asOfDate")
        if raw_value is not None:
            row[output] = _required_decimal(raw_value, output)
            observed_date = _iso_date(raw_date)
            if observed_date is None:
                raise ValueError(f"Official issuer page is missing the {output} observation date")
            row[f"{output}_as_of"] = observed_date
            base_currency = row.get("base_currency")
            if base_currency:
                row[currency_key] = base_currency

    objective = parser.features[0] if parser.features else None
    if objective and "seeks to provide investment results" in objective.casefold() and "..." not in objective and "…" not in objective:
        row["objective"] = objective

    sectors: dict[str, Decimal] = {}
    sectors_as_of: str | None = None
    raw_sectors = parser.inputs.get("fund-sector-breakdown")
    if raw_sectors:
        try:
            sectors_data = json.loads(raw_sectors)
        except json.JSONDecodeError as exc:
            raise ValueError("Official issuer page has invalid sector data") from exc
        sectors_as_of = _iso_date(sectors_data.get("asOfDate")) if isinstance(sectors_data, dict) else None
        array = sectors_data.get("attrArray", []) if isinstance(sectors_data, dict) else []
        if array and sectors_as_of is None:
            raise ValueError("Official sector data is missing its observation date")
        for item in array:
            if not isinstance(item, dict):
                continue
            name = _clean_text(_nested_value(item.get("name")))
            weight_obj = item.get("weight")
            raw_weight = weight_obj.get("originalValue") if isinstance(weight_obj, dict) else None
            if raw_weight is None and isinstance(weight_obj, dict):
                raw_weight = weight_obj.get("value")
            weight = _decimal(raw_weight)
            if name and weight is not None and Decimal("0") <= weight <= Decimal("100"):
                sectors[name] = weight / Decimal("100")
        if sectors:
            row["sectors"] = sectors
            row["sectors_as_of"] = sectors_as_of
    return row


def _column_index(cell_reference: str) -> int:
    letters = re.match(r"([A-Z]+)", cell_reference.upper())
    if not letters:
        return 0
    number = 0
    for char in letters.group(1):
        number = number * 26 + ord(char) - ord("A") + 1
    return number - 1


def _xml_text(element: ET.Element | None) -> str | None:
    if element is None:
        return None
    return "".join(part.text or "" for part in element.iter() if part.tag.rsplit("}", 1)[-1] == "t") or (element.text or None)


def _xlsx_parts(content: bytes) -> tuple[ZipFile, str, list[str]]:
    if len(content) > _HOLDINGS_MAX_BYTES:
        raise ValueError("Official holdings workbook exceeds the download size limit")
    try:
        archive = ZipFile(BytesIO(content))
    except (BadZipFile, OSError) as exc:
        raise ValueError("Official holdings workbook is not a valid XLSX file") from exc
    if sum(item.file_size for item in archive.infolist()) > _XLSX_MAX_UNCOMPRESSED_BYTES:
        archive.close()
        raise ValueError("Official holdings workbook exceeds the expanded size limit")
    try:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    except (KeyError, ET.ParseError) as exc:
        archive.close()
        raise ValueError("Official holdings workbook is missing its worksheet index") from exc
    relationship_targets = {
        item.attrib.get("Id"): item.attrib.get("Target")
        for item in relationships
        if item.attrib.get("Id") and item.attrib.get("Target")
    }
    sheet = next((item for item in workbook.iter() if item.tag.rsplit("}", 1)[-1] == "sheet"), None)
    if sheet is None:
        archive.close()
        raise ValueError("Official holdings workbook has no worksheet")
    relationship_id = next((value for key, value in sheet.attrib.items() if key.rsplit("}", 1)[-1] == "id"), None)
    target = relationship_targets.get(relationship_id)
    if not target:
        archive.close()
        raise ValueError("Official holdings workbook has no worksheet target")
    worksheet = posixpath.normpath(target.lstrip("/") if target.startswith("/") else posixpath.join("xl", target))
    if not worksheet.startswith("xl/") or worksheet.startswith("xl/../") or worksheet == "xl/..":
        archive.close()
        raise ValueError("Official holdings worksheet path is invalid")
    shared: list[str] = []
    try:
        raw_shared = archive.read("xl/sharedStrings.xml")
    except KeyError:
        raw_shared = None
    if raw_shared:
        try:
            shared_root = ET.fromstring(raw_shared)
        except ET.ParseError as exc:
            archive.close()
            raise ValueError("Official holdings workbook has invalid shared strings") from exc
        shared = ["".join((node.text or "") for node in item.iter() if node.tag.rsplit("}", 1)[-1] == "t") for item in shared_root]
    return archive, worksheet, shared


def _sheet_rows(sheet_root: ET.Element, shared: list[str]) -> list[dict[int, str]]:
    rows: list[dict[int, str]] = []
    for row in (item for item in sheet_root.iter() if item.tag.rsplit("}", 1)[-1] == "row"):
        cells: dict[int, str] = {}
        for cell in (item for item in row if item.tag.rsplit("}", 1)[-1] == "c"):
            reference = cell.attrib.get("r", "")
            column = _column_index(reference)
            value_node = next((child for child in cell if child.tag.rsplit("}", 1)[-1] == "v"), None)
            cell_type = cell.attrib.get("t")
            value: str | None
            if cell_type == "s" and value_node is not None:
                try:
                    value = shared[int(value_node.text or "")]
                except (ValueError, IndexError):
                    raise ValueError("Official holdings workbook contains an invalid shared-string index")
            elif cell_type == "inlineStr":
                value = _xml_text(next((child for child in cell if child.tag.rsplit("}", 1)[-1] == "is"), None))
            else:
                value = value_node.text if value_node is not None else None
            if value is not None:
                cells[column] = value.strip()
        rows.append(cells)
    return rows


def _parse_holdings(content: bytes, *, symbol: str) -> tuple[list[dict[str, Any]], str]:
    archive, worksheet, shared = _xlsx_parts(content)
    try:
        try:
            sheet_root = ET.fromstring(archive.read(worksheet))
        except (KeyError, ET.ParseError) as exc:
            raise ValueError("Official holdings worksheet is missing or invalid") from exc
    finally:
        archive.close()
    rows = _sheet_rows(sheet_root, shared)

    workbook_symbol: str | None = None
    holdings_date: str | None = None
    for cells in rows:
        for column, value in cells.items():
            label = value.strip().casefold()
            if label == "ticker symbol:" and column + 1 in cells:
                workbook_symbol = cells[column + 1].strip()
            elif label == "holdings:" and column + 1 in cells:
                holdings_date = _iso_date(cells[column + 1])
    if workbook_symbol is None or workbook_symbol.upper() != symbol.upper():
        raise ValueError("Official holdings workbook identity mismatch")
    if holdings_date is None:
        raise ValueError("Official holdings workbook is missing its observation date")

    headers: dict[str, int] | None = None
    header_row_index = -1
    for index, cells in enumerate(rows):
        normalized = {str(value).strip().casefold(): column for column, value in cells.items() if value.strip()}
        if "name" in normalized and "ticker" in normalized and "weight" in normalized:
            headers, header_row_index = normalized, index
            break
    if headers is None:
        raise ValueError("Official holdings workbook is missing its holdings columns")

    holdings: list[dict[str, Any]] = []
    for cells in rows[header_row_index + 1:]:
        name = cells.get(headers["name"], "").strip() or None
        ticker = cells.get(headers["ticker"], "").strip() or None
        if ticker == "-":
            ticker = None
        raw_weight = cells.get(headers["weight"])
        if raw_weight is None or not raw_weight.strip():
            # Notes after the holdings table have no weight and are not holdings.
            continue
        weight = _decimal(raw_weight)
        if weight is None or not Decimal("0") <= weight <= Decimal("100"):
            raise ValueError("Official holdings workbook contains an invalid weight")
        if not name and not ticker:
            continue
        item: dict[str, Any] = {"weight": weight / Decimal("100")}
        if ticker:
            item["symbol"] = ticker
        if name:
            item["name"] = name
        for column_name, output_name in (
            ("identifier", "identifier"),
            ("sedol", "sedol"),
            ("sector", "sector"),
            ("shares held", "shares_held"),
            ("local currency", "local_currency"),
        ):
            column = headers.get(column_name)
            value = cells.get(column, "").strip() if column is not None else ""
            if value and value != "-":
                if output_name == "shares_held":
                    parsed = _decimal(value)
                    if parsed is not None:
                        item[output_name] = parsed
                else:
                    item[output_name] = value
        holdings.append(item)
    if not holdings:
        raise ValueError("Official holdings workbook contains no holdings")
    return holdings, holdings_date


def _bounded_download(url: str, *, max_bytes: int) -> bytes:
    parsed = urlparse(url)
    if url not in {_PAGE_URL, _HOLDINGS_URL} or parsed.scheme != "https" or parsed.hostname != "www.ssga.com" or parsed.username or parsed.password:
        raise ValueError("Official issuer URL is outside the fixed State Street host")
    session = _bounded_yahoo_session()
    response = session.get(url, timeout=_FETCH_TIMEOUT_SECONDS, stream=True, allow_redirects=False)
    try:
        if response.status_code != 200:
            raise RuntimeError(f"Official issuer request returned HTTP {response.status_code}")
        if urlparse(response.url).hostname != "www.ssga.com":
            raise RuntimeError("Official issuer request left the State Street host")
        declared_length = response.headers.get("Content-Length")
        if declared_length:
            try:
                if int(declared_length) > max_bytes:
                    raise RuntimeError("Official issuer response exceeds the size limit")
            except ValueError:
                pass
        chunks: list[bytes] = []
        size = 0
        deadline = time.monotonic() + _FETCH_TIMEOUT_SECONDS
        for chunk in response.iter_content(chunk_size=64 * 1024):
            if time.monotonic() >= deadline:
                raise RuntimeError("Official issuer response exceeded the download time limit")
            if not chunk:
                continue
            size += len(chunk)
            if size > max_bytes:
                raise RuntimeError("Official issuer response exceeds the size limit")
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        response.close()


def _download_official_data(symbol: str) -> dict[str, Any]:
    if not supports_issuer_fund_data(symbol):
        raise ValueError("Issuer fund data is unsupported for this symbol")
    page_bytes = _bounded_download(_PAGE_URL, max_bytes=_PAGE_MAX_BYTES)
    workbook = _bounded_download(_HOLDINGS_URL, max_bytes=_HOLDINGS_MAX_BYTES)
    row = _parse_page(page_bytes.decode("utf-8", errors="replace"), symbol=_SYMBOL, expected_isin=_ISIN)
    holdings, holdings_as_of = _parse_holdings(workbook, symbol=_SYMBOL)
    return {**row, "holdings": holdings, "holdings_as_of": holdings_as_of,
            "holdings_complete": True, "holdings_url": _HOLDINGS_URL}


def fetch_issuer_fund_data(symbol: str) -> ResearchData | None:
    normalized = symbol.strip().upper() if isinstance(symbol, str) else ""
    if not supports_issuer_fund_data(normalized):
        return None
    try:
        result = run_async(
            IssuerFundDataFetcher.fetch_data,
            {"symbol": normalized},
            credentials=None,
        )
        row = result.model_dump(mode="json") if hasattr(result, "model_dump") else dict(result)
    except Exception as exc:
        raise ResearchProviderError(
            "State Street issuer fund data retrieval failed.",
            provider=_PROVIDER,
            public_message="Issuer fund information and official holdings are currently unavailable.",
        ) from exc
    return ResearchData(
        symbol=normalized,
        asset_type="etf",
        category="issuer_fund_data",
        provider=_PROVIDER,
        retrieved_at=datetime.now(timezone.utc),
        data=(row,),
        attempts=(ProviderAttempt(_PROVIDER, "success"),),
        request_parameters=(("source_url", _PAGE_URL), ("holdings_url", _HOLDINGS_URL)),
    )
