"""Developer-only probe for the OpenBB research adapter; no Gemini involved."""

from pprint import pprint
from pathlib import Path
import sys

# Allow `python scripts/openbb_research_probe.py` from any working directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.trading.research import OpenBBResearchClient, ResearchError


def _show(label: str, result) -> None:
    print(f"\n{label}: provider={result.provider}, rows={len(result.data)}")
    pprint(result.data[0])


def main() -> None:
    client = OpenBBResearchClient()
    checks = (
        ("NVDA price history", lambda: client.get_price_history("NVDA", start_date="2026-08-01", end_date="2026-08-08")),
        ("NVDA company profile", lambda: client.get_company_profile("NVDA")),
        ("NVDA income statement", lambda: client.get_financial_statements("NVDA", statement="income", limit=1)),
        ("BTC price history", lambda: client.get_price_history("BTC-USD", asset_type="crypto", start_date="2026-08-01", end_date="2026-08-08")),
        ("US CPI", lambda: client.get_macro_series("CPI", start_date="2026-01-01", end_date="2026-06-01")),
    )
    for label, query in checks:
        try:
            _show(label, query())
        except ResearchError as exc:
            print(f"\n{label}: {exc.code} ({exc.provider or 'default provider'}): {exc}")


if __name__ == "__main__":
    main()
