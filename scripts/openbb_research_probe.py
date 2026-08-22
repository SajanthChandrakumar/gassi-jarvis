"""Opt-in OpenBB coverage probe; prints metadata only and never credentials or values."""

from datetime import date, timedelta
import logging
from pathlib import Path
import sys

from dotenv import load_dotenv

# Allow `python scripts/openbb_research_probe.py` from any working directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.trading.research import OpenBBResearchClient, ResearchData, ResearchError


def summarize(label: str, result: ResearchData) -> None:
    fields = sorted({key for row in result.data[:3] for key, value in row.items() if value is not None})
    attempts = ",".join(f"{item.provider}:{item.outcome}" for item in result.attempts)
    print(f"{label}|provider={result.provider}|rows={len(result.data)}|fields={','.join(fields)}|attempts={attempts}")


def main() -> None:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    logging.getLogger("asyncio").setLevel(logging.CRITICAL)
    client = OpenBBResearchClient()
    today = date.today()
    start = today - timedelta(days=30)
    earnings_start = today - timedelta(days=14)
    earnings_end = today + timedelta(days=30)
    macro_start = today - timedelta(days=730)
    checks = (
        ("nvda_price", lambda: client.get_price_history("NVDA", start_date=start, end_date=today)),
        ("nvda_quote", lambda: client.get_equity_quote("NVDA")),
        ("nvda_profile", lambda: client.get_company_profile("NVDA")),
        ("nvda_income", lambda: client.get_financial_statements("NVDA", statement="income", limit=1)),
        ("nvda_metrics", lambda: client.get_fundamental_metrics("NVDA")),
        ("nvda_estimates", lambda: client.get_estimates_consensus("NVDA")),
        ("nvda_earnings", lambda: client.get_earnings_calendar("NVDA", start_date=earnings_start, end_date=earnings_end)),
        ("nvda_filings", lambda: client.get_company_filings("NVDA", limit=5)),
        ("nvda_news", lambda: client.get_company_news("NVDA", limit=3, provider="yfinance")),
        ("macro_inflation", lambda: client.get_macro_series("inflation", series_id="CPIAUCSL", transform="pc1", unit="% YoY", start_date=macro_start, end_date=today)),
        ("macro_unemployment", lambda: client.get_macro_series("unemployment", series_id="UNRATE", unit="%", start_date=macro_start, end_date=today)),
        ("macro_policy_rate", lambda: client.get_macro_series("policy_rate", series_id="FEDFUNDS", unit="%", start_date=macro_start, end_date=today)),
        ("macro_treasury_10y", lambda: client.get_macro_series("treasury_10y", series_id="DGS10", unit="%", start_date=macro_start, end_date=today)),
        ("macro_real_gdp_growth", lambda: client.get_macro_series("real_gdp_growth", series_id="GDPC1", transform="pc1", unit="% YoY", start_date=macro_start, end_date=today)),
        ("btc_price", lambda: client.get_price_history("BTC", asset_type="crypto", start_date=start, end_date=today)),
        ("eth_price", lambda: client.get_price_history("ETH", asset_type="crypto", start_date=start, end_date=today)),
    )
    for label, query in checks:
        try:
            summarize(label, query())
        except ResearchError as exc:
            print(f"{label}|error={type(exc).__name__}|code={exc.code}|provider={exc.provider or 'none'}")
        except Exception as exc:
            print(f"{label}|error={type(exc).__name__}|code=unexpected|provider=none")


if __name__ == "__main__":
    main()
