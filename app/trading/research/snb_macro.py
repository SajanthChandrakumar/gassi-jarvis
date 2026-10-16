"""Allowlisted Swiss official series using the existing OpenBB Fetcher pipeline.

SNB republishes national BFS/SECO statistics alongside its own observations.
No proxies, transformations, credentials, or dynamically supplied URLs.
"""

from calendar import monthrange
import csv
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from io import StringIO
import re
from types import SimpleNamespace
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.economic_indicators import (
    EconomicIndicatorsData, EconomicIndicatorsQueryParams,
)
from openbb_core.provider.utils.helpers import make_request, run_async


@dataclass(frozen=True)
class SwissSeries:
    cube: str
    dimensions: tuple[tuple[str, str], ...]
    topic: str
    title: str
    definition: str
    source_name: str
    frequency: str
    unit: str

    @property
    def selector(self) -> str:
        return ",".join(f"{key}({value})" for key, value in self.dimensions)

    @property
    def source_url(self) -> str:
        return f"https://data.snb.ch/en/topics/{self.topic}/cube/{self.cube}?" + urlencode({"dimSel": self.selector})


SWISS_SERIES = {
    "inflation": SwissSeries("plkopr", (("D0", "VVP"),), "uvo", "CPI inflation (BFS)",
        "National CPI, change from the same month a year earlier.", "BFS via SNB", "month", "% YoY"),
    "unemployment": SwissSeries("amarbma", (("D0", "T1"),), "uvo", "Registered unemployment (SECO)",
        "Registered unemployment rate, not seasonally adjusted (not ILO unemployment).", "SECO via SNB", "month", "%"),
    "policy_rate": SwissSeries("snbgwdzid", (("D0", "LZ"),), "snb", "SNB policy rate",
        "Official SNB policy rate, daily observation (not an interbank proxy).", "SNB", "day", "%"),
    "treasury_10y": SwissSeries("rendeiduebm", (("D0", "CHF"), ("D1", "10J")), "ziredev", "10-year Confederation spot yield",
        "Swiss Confederation zero-coupon spot yield, 10-year maturity, end of month (2025 methodology).", "SNB", "month", "%"),
    "real_gdp_growth": SwissSeries("gdprpq", (("D0", "VVK"), ("D1", "BBIPS")), "uvo", "Real GDP growth (SECO)",
        "Change from previous quarter; seasonally, calendar and sports-event adjusted.", "SECO via SNB", "quarter", "% QoQ"),
}


class SnbMacroData(EconomicIndicatorsData):
    value: Decimal
    title: str
    frequency: str
    unit: str
    period: str
    definition: str
    source_name: str
    source_url: str
    published_at: datetime


def _period_end(period: str, frequency: str) -> date:
    if frequency == "day":
        return date.fromisoformat(period)
    if frequency == "month" and re.fullmatch(r"\d{4}-\d{2}", period):
        year, month = map(int, period.split("-"))
    elif frequency == "quarter" and re.fullmatch(r"\d{4}-Q[1-4]", period):
        year, quarter = period.split("-Q")
        year, month = int(year), int(quarter) * 3
    else:
        raise ValueError("SNB returned an invalid observation period.")
    return date(year, month, monthrange(year, month)[1])


class SnbMacroFetcher(Fetcher[EconomicIndicatorsQueryParams, list[SnbMacroData]]):
    require_credentials = False

    @staticmethod
    def transform_query(params: dict) -> EconomicIndicatorsQueryParams:
        query = EconomicIndicatorsQueryParams(**params)
        if query.symbol not in SWISS_SERIES or query.country != "switzerland":
            raise ValueError("SNB supports only the allowlisted Swiss indicators.")
        query.end_date = query.end_date or date.today()
        query.start_date = query.start_date or query.end_date - timedelta(days=730)
        if not 0 <= (query.end_date - query.start_date).days <= 3660 or query.end_date > date.today():
            raise ValueError("SNB requires a past or current, bounded date range (maximum ten years).")
        return query

    @staticmethod
    def extract_data(query: EconomicIndicatorsQueryParams, credentials: dict | None, **_) -> str:
        spec = SWISS_SERIES[query.symbol]
        response = make_request(
            f"https://data.snb.ch/api/cube/{spec.cube}/data/csv/en",
            params={"dimSel": spec.selector, "fromDate": query.start_date.isoformat(), "toDate": query.end_date.isoformat()},
            timeout=10, allow_redirects=False,
        )
        response.raise_for_status()
        if response.status_code != 200 or len(response.text) > 2_000_000:
            raise ValueError("SNB returned an unexpected response.")
        return response.text

    @staticmethod
    def transform_data(query: EconomicIndicatorsQueryParams, data: str, **_) -> list[SnbMacroData]:
        spec = SWISS_SERIES[query.symbol]
        reader = csv.reader(StringIO(data.lstrip("\ufeff")), delimiter=";", strict=True)
        metadata = {}
        for row in reader:
            if row and row[0] == "Date":
                header = row
                break
            if len(row) == 2:
                if row[0] in metadata:
                    raise ValueError("SNB CSV has duplicate metadata.")
                metadata[row[0]] = row[1]
        else:
            raise ValueError("SNB CSV has no observation header.")
        if metadata.get("CubeId") != spec.cube or header != ["Date", *(key for key, _ in spec.dimensions), "Value"]:
            raise ValueError("SNB CSV cube or dimensions do not match the requested series.")
        published = datetime.fromisoformat(metadata.get("PublishingDate", ""))
        if published.tzinfo is None:
            published = published.replace(tzinfo=ZoneInfo("Europe/Zurich"))
        published = published.astimezone(timezone.utc)
        if published > datetime.now(timezone.utc) + timedelta(minutes=5):
            raise ValueError("SNB publication date is in the future.")
        observations = []
        periods = set()
        for row in reader:
            if not row:
                continue
            if len(row) != len(header):
                raise ValueError("SNB CSV observation has unexpected columns.")
            if tuple(row[1:-1]) != tuple(value for _, value in spec.dimensions):
                continue
            observed = _period_end(row[0], spec.frequency)
            if not query.start_date <= observed <= query.end_date:
                continue
            if row[0] in periods:
                raise ValueError("SNB returned duplicate observations for the same period.")
            periods.add(row[0])
            if not row[-1].strip():
                continue  # Missing observations are not zeros or substituted values.
            value = Decimal(row[-1])
            if not value.is_finite():
                raise ValueError("SNB returned a non-finite value.")
            observations.append(SnbMacroData(
                date=observed, symbol=query.symbol.upper(), country="switzerland", value=value,
                title=spec.title, frequency=spec.frequency, unit=spec.unit, period=row[0],
                definition=spec.definition, source_name=spec.source_name, source_url=spec.source_url,
                published_at=published,
            ))
        return sorted(observations, key=lambda row: row.date)


def fetch_swiss_macro(**params):
    """Return the same results/provider envelope consumed by the OpenBB adapter."""
    return SimpleNamespace(results=run_async(SnbMacroFetcher.fetch_data, params=params), provider="snb", warnings=[])
