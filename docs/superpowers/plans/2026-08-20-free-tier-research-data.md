# Free-Tier Research Data Implementation Plan

> Historical plan: Benzinga and Tiingo were removed on 2026-10-02, and the
> OpenBB metapackage was replaced by pinned components. Use
> [OpenBB research](../../openbb-research.md) for current installation and
> provider configuration; the snippets below describe the original plan.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand Jarvis' canonical research output to the maximum essential evidence verified on the configured free tiers, with endpoint-specific fallbacks and truthful quality/provenance.

**Architecture:** Keep OpenBB behind `OpenBBResearchClient`, add endpoint-specific provider chains, and normalize quote, metrics, filings, earnings, news, and macro observations into immutable canonical models. The planner requests only bounded sections; report and API layers serialize observed values and stable failure codes without provider exception text.

**Tech Stack:** Python 3.13 virtual environment, OpenBB 4.7.2, dataclasses, Decimal, FastAPI 0.136.3, Pydantic 2.13.3, pytest.

**Spec:** `docs/superpowers/specs/2026-08-20-research-first-command-center-design.md`

## Global Constraints

- Keep `LLM != Quant Engine`; Gemini must not calculate, fill, rank, or override financial evidence.
- Preserve `None`, provider, request scope, `as_of`, `retrieved_at`, freshness, quality, availability, and failures.
- Never return another company's calendar row or a loosely related headline as evidence for the requested asset.
- Do not bypass a provider entitlement or scrape a provider website.
- Standard tests must not use network access or credentials.
- Keep `openbb==4.7.2`, `fastapi==0.136.3`, and `uvicorn==0.40.0` pinned.
- Do not add recommendations, portfolios, scanning, alerts, trading, or execution.
- Never print, serialize, log into fixtures, or commit credential values.

## File map

- `app/trading/research/openbb_client.py`: OpenBB routes, provider chains, safe provider attempts.
- `app/trading/research/canonical.py`: immutable quote and filing models and aggregate fields.
- `app/trading/research/normalizers.py`: schema conversion and deterministic relevance/quality rules.
- `app/trading/research/service.py`: selective section aggregation, caching, and bounded calendar scope.
- `app/trading/research/freshness.py`: TTLs for new categories.
- `app/trading/research/orchestration.py`: approved section plans only.
- `app/trading/research/reports.py`: report-level quote and filings payloads.
- `app/trading/research/report_service.py`: document-oriented observed report sections.
- `app/trading/research/jarvis_tools.py`: safe response wording and macro specification.
- `app/trading/research/provider_status.py`: configuration-state vocabulary.
- `app/trading/research/__init__.py`: public canonical exports.
- `app/main.py`, `app/models.py`: retain authenticated bounded HTTP contracts.
- `tests/trading/*`, `tests/test_*endpoint.py`: credential-free fixtures and API contracts.
- `docs/*.md`, `architecture.md`: finalized provider and canonical contracts.

---

### Task 1: Safe endpoint-specific provider attempts

**Files:**
- Modify: `app/trading/research/canonical.py`
- Modify: `app/trading/research/openbb_client.py:20-465`
- Modify: `app/trading/research/normalizers.py`
- Modify: `app/trading/research/__init__.py`
- Modify: `tests/trading/test_openbb_client.py:1-270`
- Modify: `tests/trading/test_canonical_research.py`

**Interfaces:**
- Produces: canonical `ProviderAttempt(provider: str | None, outcome: str, code: str | None)`.
- Produces: `ResearchData.attempts: tuple[ProviderAttempt, ...]`.
- Preserves: attempts in `ResearchProvenance.attempts` through every normalizer.
- Produces: module helper `_first_available(providers, request) -> ResearchData`.
- Consumes: existing `ResearchError.code` subclasses and explicit `provider=` overrides.

- [ ] **Step 1: Write failing provider-chain and sanitization tests**

```python
def test_default_provider_chain_records_failed_attempt_and_success():
    providers = []
    def historical(**kwargs):
        providers.append(kwargs["provider"])
        if kwargs["provider"] == "yfinance":
            return FakeResult([], provider="yfinance")
        return FakeResult([FakeRow(date="2026-08-20", close=10)], provider="tiingo")

    client = OpenBBResearchClient(
        _fake_openbb(equity_price=historical),
        ResearchProviderSettings(price=("yfinance", "tiingo", "fmp")),
    )
    result = client.get_price_history("NVDA")

    assert providers == ["yfinance", "tiingo"]
    assert [(item.provider, item.outcome, item.code) for item in result.attempts] == [
        ("yfinance", "failure", "no_data"),
        ("tiingo", "success", None),
    ]


def test_explicit_provider_never_falls_through():
    client = OpenBBResearchClient(_fake_openbb(equity_price=lambda **_: FakeResult([])))
    with pytest.raises(ResearchNoDataError):
        client.get_price_history("NVDA", provider="yfinance")


def test_provider_error_has_stable_public_message():
    error = OpenBBResearchClient._map_openbb_error(
        RuntimeError("402 Restricted Endpoint: upgrade at https://provider.invalid/plan"),
        "fmp",
    )
    assert error.code == "entitlement_required"
    assert error.public_message == "This data is not included in the configured FMP tier."
    assert "http" not in error.public_message


def test_provider_attempts_survive_canonical_normalization():
    raw = _raw("price_history", [{"date": "2026-08-20", "close": 10}], provider="tiingo")
    raw = replace(raw, attempts=(
        ProviderAttempt("yfinance", "failure", "no_data"),
        ProviderAttempt("tiingo", "success", None),
    ))
    normalized = normalize_price_data(raw, ASSET, now=NOW)
    assert normalized.provenance.attempts == raw.attempts
```

- [ ] **Step 2: Run the focused tests and confirm the red state**

Run: `.venv/bin/pytest tests/trading/test_openbb_client.py -k "provider_chain or explicit_provider or public_message" -v`

Expected: FAIL because `price`, `ProviderAttempt`, `attempts`, and `public_message` do not exist.

- [ ] **Step 3: Add provider-attempt types and a single fallback helper**

```python
@dataclass(frozen=True, slots=True)
class ProviderAttempt:
    provider: str | None
    outcome: Literal["success", "failure"]
    code: str | None = None


# Add to ResearchProvenance in canonical.py:
attempts: tuple[ProviderAttempt, ...] = ()


@dataclass(frozen=True, slots=True)
class ResearchProviderSettings:
    price: tuple[str, ...] = ("yfinance",)
    quote: tuple[str, ...] = ("yfinance",)
    profile: tuple[str, ...] = ("yfinance",)
    statements: tuple[str, ...] = ("yfinance",)
    metrics: tuple[str, ...] = ("yfinance",)
    news: tuple[str, ...] = ("yfinance",)
    estimates: tuple[str, ...] = ("yfinance",)
    earnings: tuple[str, ...] = ()
    filings: tuple[str, ...] = ("sec",)
    crypto: tuple[str, ...] = ("yfinance",)
    macro: tuple[str, ...] = ("econdb",)


def _first_available(
    providers: tuple[str, ...],
    request: Callable[[str], ResearchData],
) -> ResearchData:
    attempts: list[ProviderAttempt] = []
    last_error: ResearchError | None = None
    for provider in providers:
        try:
            result = request(provider)
        except ResearchError as exc:
            attempts.append(ProviderAttempt(provider, "failure", exc.code))
            last_error = exc
            continue
        attempts.append(ProviderAttempt(provider, "success"))
        return replace(result, attempts=tuple(attempts))
    if last_error is not None:
        raise last_error
    raise ResearchConfigurationError("No provider is configured for this route.")
```

Add `attempts: tuple[ProviderAttempt, ...] = ()` to `ResearchData`. Build chains in
`ResearchProviderSettings.from_environment()` only from credential-free or
configured providers. Map 402/restricted/premium errors to
`ResearchEntitlementError(code="entitlement_required")`; give every
`ResearchError` a stable `public_message` while keeping `str(exc)` for server
diagnostics.

```python
class ResearchError(RuntimeError):
    code = "research_error"

    def __init__(self, message: str, *, provider: str | None = None, public_message: str | None = None):
        super().__init__(message)
        self.provider = provider
        self.public_message = public_message or "Research data is currently unavailable."


class ResearchEntitlementError(ResearchError):
    code = "entitlement_required"
```

Update `_provenance(raw, ...)` to pass `attempts=raw.attempts`. Add a canonical
test proving a failed first provider and successful fallback survive
normalization as structured provenance without raw exception text.

Use this exact environment policy:

```python
@classmethod
def from_environment(cls) -> "ResearchProviderSettings":
    has_fmp = bool(os.getenv("FMP_API_KEY", "").strip())
    has_tiingo = bool(os.getenv("TIINGO_TOKEN", "").strip())
    has_fred = bool(os.getenv("FRED_API_KEY", "").strip())
    return cls(
        price=("yfinance",) + (("tiingo",) if has_tiingo else ()) + (("fmp",) if has_fmp else ()),
        quote=("yfinance",) + (("fmp",) if has_fmp else ()),
        profile=(("fmp",) if has_fmp else ()) + ("yfinance",),
        statements=("sec",) + (("fmp",) if has_fmp else ()) + ("yfinance",),
        metrics=(("fmp",) if has_fmp else ()) + ("yfinance",),
        news=("yfinance",),
        estimates=(("fmp",) if has_fmp else ()) + ("yfinance",),
        earnings=(("fmp",) if has_fmp else ()),
        filings=("sec",),
        crypto=("yfinance",),
        macro=(("fred",) if has_fred else ()) + ("econdb",),
    )
```

- [ ] **Step 4: Apply the helper to price history without changing explicit overrides**

```python
providers = (provider,) if provider else self._provider_settings.price
return _first_available(providers, lambda selected: self._execute(
    lambda: endpoint(**{**params, "provider": selected}),
    symbol=symbol,
    asset_type=asset_type,
    category="price_history",
    requested_provider=selected,
    start_date=params["start_date"],
    end_date=params["end_date"],
))
```

- [ ] **Step 5: Apply the helper to profile and estimates**

```python
def get_company_profile(self, symbol: str, *, provider: str | None = None) -> ResearchData:
    providers = (provider,) if provider else self._provider_settings.profile
    return _first_available(providers, lambda selected: self._execute(
        lambda: self._obb.equity.profile(symbol=symbol, provider=selected),
        symbol=symbol, asset_type="equity", category="company_profile",
        requested_provider=selected,
    ))


def get_estimates_consensus(self, symbol: str, *, provider: str | None = None) -> ResearchData:
    providers = (provider,) if provider else self._provider_settings.estimates
    return _first_available(providers, lambda selected: self._execute(
        lambda: self._obb.equity.estimates.consensus(symbol=symbol, provider=selected),
        symbol=symbol, asset_type="equity", category="estimates_consensus",
        requested_provider=selected,
    ))
```

Update the `_client` test helper to construct all tuple routes explicitly:

```python
ResearchProviderSettings(
    price=("equity-default",), quote=("equity-default",),
    profile=("equity-default",), statements=("equity-default",),
    metrics=("equity-default",), news=("news-default",),
    estimates=("estimates-default",), earnings=("fmp",), filings=("sec",),
    crypto=("crypto-default",), macro=("macro-default",),
)
```

- [ ] **Step 6: Run all OpenBB adapter tests**

Run: `.venv/bin/pytest tests/trading/test_openbb_client.py tests/trading/test_canonical_research.py -v`

Expected: PASS; existing fallback assertions are updated to inspect attempts and
the successful provider instead of parsing warning prose.

- [ ] **Step 7: Commit the provider-attempt boundary**

```bash
git add app/trading/research/canonical.py app/trading/research/openbb_client.py app/trading/research/normalizers.py app/trading/research/__init__.py tests/trading/test_openbb_client.py tests/trading/test_canonical_research.py
git commit -m "refactor(research): add endpoint provider attempts"
```

---

### Task 2: Canonical equity quote and valuation metrics

**Files:**
- Modify: `app/trading/research/canonical.py:95-330`
- Modify: `app/trading/research/openbb_client.py:150-380`
- Modify: `app/trading/research/normalizers.py:120-330`
- Modify: `app/trading/research/service.py:25-230`
- Modify: `app/trading/research/freshness.py:10-30`
- Modify: `app/trading/research/__init__.py:1-125`
- Modify: `tests/trading/test_openbb_client.py`
- Modify: `tests/trading/test_canonical_research.py`

**Interfaces:**
- Produces: `EquityQuote` canonical dataclass.
- Produces: `OpenBBResearchClient.get_equity_quote(symbol, provider=None)`.
- Produces: `OpenBBResearchClient.get_fundamental_metrics(symbol, provider=None)`.
- Produces: `normalize_equity_quote(raw, asset, ...) -> EquityQuote`.
- Produces: `normalize_valuation_metrics(raw, asset, ...) -> ValuationData`.
- Produces: `AssetResearchData.quote` and service sections `quote`, `valuation`.

- [ ] **Step 1: Write failing adapter and normalizer tests**

```python
def test_quote_and_metrics_use_dedicated_routes():
    quote_args, metric_args = {}, {}
    client = _client(
        quote=lambda **kwargs: quote_args.update(kwargs) or FakeResult([
            FakeRow(symbol="NVDA", last_price=216.61, prev_close=214.40,
                    year_high=225, year_low=86, currency="USD")
        ], provider="yfinance"),
        metrics=lambda **kwargs: metric_args.update(kwargs) or FakeResult([
            FakeRow(symbol="NVDA", market_cap=5_250_000_000_000,
                    pe_ratio=31.8, forward_pe=28.1, enterprise_value=5_100_000_000_000,
                    ev_to_ebitda=25.2, free_cash_flow_yield=0.021)
        ], provider="fmp"),
    )
    assert client.get_equity_quote("NVDA", provider="yfinance").category == "equity_quote"
    assert client.get_fundamental_metrics("NVDA", provider="fmp").category == "fundamental_metrics"
    assert quote_args == {"symbol": "NVDA", "provider": "yfinance"}
    assert metric_args == {"symbol": "NVDA", "provider": "fmp"}


def test_quote_and_metrics_normalize_only_observed_values():
    quote = normalize_equity_quote(_raw("equity_quote", [{
        "last_price": 216.61, "prev_close": 214.40, "year_high": 225,
        "year_low": 86, "volume": 12_000, "currency": "USD",
    }]), ASSET, now=NOW)
    valuation = normalize_valuation_metrics(_raw("fundamental_metrics", [{
        "market_cap": 5_250_000_000_000, "pe_ratio": 31.8,
        "forward_pe": None, "ev_to_ebitda": 25.2,
    }]), ASSET, now=NOW)

    assert quote.last_price == Decimal("216.61")
    assert quote.previous_close == Decimal("214.40")
    assert dict(valuation.metrics) == {
        "ev_to_ebitda": Decimal("25.2"),
        "market_cap": Decimal("5250000000000"),
        "pe_ratio": Decimal("31.8"),
    }
```

- [ ] **Step 2: Run the new tests and confirm they fail**

Run: `.venv/bin/pytest tests/trading/test_openbb_client.py tests/trading/test_canonical_research.py -k "quote or metrics" -v`

Expected: FAIL with missing routes and canonical types.

- [ ] **Step 3: Add the canonical quote and aggregate field**

```python
@dataclass(frozen=True, slots=True)
class EquityQuote:
    asset: AssetIdentity
    last_price: Decimal | None
    previous_close: Decimal | None
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    volume: Decimal | None
    year_high: Decimal | None
    year_low: Decimal | None
    moving_average_50d: Decimal | None
    moving_average_200d: Decimal | None
    currency: str | None
    provenance: ResearchProvenance
    as_of: datetime | None
    freshness: FreshnessStatus
    quality: DataQuality
```

Add `quote: EquityQuote | None = None` before `prices` in `AssetResearchData`.
Add `equity_quote: 15 minutes` and `fundamental_metrics: 1 day` TTLs.

- [ ] **Step 4: Add OpenBB quote and metrics routes**

```python
def get_equity_quote(self, symbol: str, *, provider: str | None = None) -> ResearchData:
    providers = (provider,) if provider else self._provider_settings.quote
    return _first_available(providers, lambda selected: self._execute(
        lambda: self._obb.equity.price.quote(symbol=symbol, provider=selected),
        symbol=symbol, asset_type="equity", category="equity_quote",
        requested_provider=selected,
    ))


def get_fundamental_metrics(self, symbol: str, *, provider: str | None = None) -> ResearchData:
    providers = (provider,) if provider else self._provider_settings.metrics
    return _first_available(providers, lambda selected: self._execute(
        lambda: self._obb.equity.fundamental.metrics(symbol=symbol, provider=selected),
        symbol=symbol, asset_type="equity", category="fundamental_metrics",
        requested_provider=selected,
    ))
```

Extend `_fake_openbb` with `equity.price.quote` and
`equity.fundamental.metrics` fixtures.

- [ ] **Step 5: Normalize quote and metrics and fetch them selectively**

```python
_VALUATION_FIELDS = {
    "market_cap": ("market_cap",),
    "enterprise_value": ("enterprise_value",),
    "pe_ratio": ("pe_ratio",),
    "forward_pe": ("forward_pe",),
    "price_to_sales": ("price_to_sales", "price_to_revenue"),
    "price_to_book": ("price_to_book",),
    "ev_to_ebitda": ("ev_to_ebitda", "enterprise_to_ebitda"),
    "free_cash_flow_yield": ("free_cash_flow_yield",),
    "revenue_growth": ("revenue_growth",),
    "earnings_growth": ("earnings_growth", "net_income_growth"),
    "gross_margin": ("gross_margin",),
    "operating_margin": ("operating_margin", "ebit_margin"),
    "return_on_equity": ("return_on_equity",),
}
```

Only include a metric in `ValuationData.metrics` when its upstream value is not
`None`; do not turn absent optional metrics into a partial section. In
`CanonicalResearchService`, fetch `quote` and `valuation` independently and add
their categories and provider to the cache key.

Change `normalize_profile` to return only `CompanyProfile`; valuation no longer
comes from the profile row:

```python
def normalize_profile(
    raw: ResearchData,
    asset: AssetIdentity,
    *,
    policy: FreshnessPolicy | None = None,
    now: datetime | None = None,
) -> CompanyProfile:
    freshness = (policy or FreshnessPolicy()).status_for(raw.category, raw.retrieved_at, now=now)
    return CompanyProfile(
        asset=asset,
        provenance=_provenance(raw),
        as_of=None,
        freshness=freshness,
        quality=_quality(has_data=bool(raw.data), warnings=raw.warnings, missing_fields=(), freshness=freshness),
    )
```

For quote `as_of`, use the provider's timezone-aware `last_timestamp` when
present and otherwise leave it `None`; `retrieved_at` remains available in
provenance and must not be relabeled as a market observation time.

- [ ] **Step 6: Run canonical and adapter suites**

Run: `.venv/bin/pytest tests/trading/test_openbb_client.py tests/trading/test_canonical_research.py -v`

Expected: PASS.

- [ ] **Step 7: Commit quote and metrics**

```bash
git add app/trading/research/canonical.py app/trading/research/openbb_client.py app/trading/research/normalizers.py app/trading/research/service.py app/trading/research/freshness.py app/trading/research/__init__.py tests/trading/test_openbb_client.py tests/trading/test_canonical_research.py
git commit -m "feat(research): add quote and valuation metrics"
```

---

### Task 3: Provider-neutral fundamentals with correct quality

**Files:**
- Modify: `app/trading/research/openbb_client.py:225-260`
- Modify: `app/trading/research/normalizers.py:165-260`
- Modify: `app/trading/research/service.py:105-130`
- Modify: `tests/trading/test_openbb_client.py`
- Modify: `tests/trading/test_canonical_research.py`

**Interfaces:**
- Consumes: `ResearchProviderSettings.statements` and `ResearchData.attempts`.
- Produces: normalized SEC/FMP/Yahoo statements with latest-period missing-field semantics.

- [ ] **Step 1: Write failing provider-alias and empty-period tests**

```python
def test_fundamentals_drop_fully_empty_rows_and_use_latest_valid_period_for_quality():
    income = _raw("income_statement", [
        {"period_ending": "2026-01-31", "fiscal_period": "FY",
         "total_revenue": 100, "operating_income": 30, "net_income": 22},
        {"period_ending": "2022-01-31", "fiscal_period": "FY",
         "total_revenue": None, "operating_income": None, "net_income": None},
    ])
    result = normalize_fundamentals((("income", income),), ASSET, now=NOW)
    assert len(result.statements) == 1
    assert result.quality.status is QualityStatus.COMPLETE
    assert result.quality.missing_fields == ()


def test_sec_statement_aliases_map_to_canonical_fields():
    raw = _raw("balance_statement", [{
        "period_ending": "2026-01-31", "fiscal_period": "FY",
        "total_assets": 120, "long_term_debt": 18,
        "cash_and_equivalents": 20, "common_equity": 70,
    }], provider="sec")
    result = normalize_fundamentals((("balance", raw),), ASSET, now=NOW)
    assert dict(result.statements[0].values) == {
        "cash": Decimal("20"), "equity": Decimal("70"),
        "total_assets": Decimal("120"), "total_debt": Decimal("18"),
    }
```

- [ ] **Step 2: Run the tests and confirm the current false-partial behavior**

Run: `.venv/bin/pytest tests/trading/test_canonical_research.py -k "fundamentals or sec_statement" -v`

Expected: FAIL because the empty 2022 row remains and SEC aliases are absent.

- [ ] **Step 3: Expand aliases and discard only canonically empty rows**

```python
"balance": {
    "total_assets": ("total_assets",),
    "total_debt": ("total_debt", "long_term_debt", "long_term_debt_and_capital_lease_obligation"),
    "cash": ("cash_and_cash_equivalents", "cash_cash_equivalents_and_short_term_investments", "cash_and_equivalents", "cash_and_short_term_investments"),
    "equity": ("stockholders_equity", "total_stockholders_equity", "total_equity_gross_minority_interest", "common_stock_equity", "total_common_equity", "common_equity"),
},
```

For each statement type, normalize all rows, skip a row when every canonical
value is `None`, and compute missing concepts from the most recent retained row
for that statement type. Preserve older valid rows even if they have a narrower
schema.

- [ ] **Step 4: Use the statement provider chain for each statement route**

```python
providers = (provider,) if provider else self._provider_settings.statements
return _first_available(providers, lambda selected: self._execute(
    lambda: endpoint(symbol=symbol, limit=limit, provider=selected),
    symbol=symbol, asset_type="equity",
    category=f"{statement}_statement", requested_provider=selected,
))
```

Configure `("sec", "fmp", "yfinance")` when FMP is configured, otherwise
`("sec", "yfinance")`. An SEC no-data result for non-US assets must fall
through without turning a successful later result into partial.

- [ ] **Step 5: Run adapter, canonical, relevance, and report tests**

Run: `.venv/bin/pytest tests/trading/test_openbb_client.py tests/trading/test_canonical_research.py tests/trading/test_relevance_engine.py tests/trading/test_asset_research_reports.py -v`

Expected: PASS.

- [ ] **Step 6: Commit fundamentals quality and routing**

```bash
git add app/trading/research/openbb_client.py app/trading/research/normalizers.py app/trading/research/service.py tests/trading/test_openbb_client.py tests/trading/test_canonical_research.py
git commit -m "fix(research): normalize free-tier fundamentals"
```

---

### Task 4: Bounded, symbol-safe earnings

**Files:**
- Modify: `app/trading/research/openbb_client.py:260-290`
- Modify: `app/trading/research/normalizers.py:285-325`
- Modify: `app/trading/research/service.py:125-145`
- Modify: `app/trading/research/orchestration.py:215-265`
- Modify: `tests/trading/test_openbb_client.py`
- Modify: `tests/trading/test_canonical_research.py`
- Modify: `tests/trading/test_research_orchestration.py`

**Interfaces:**
- Produces: `get_earnings_calendar(symbol, start_date, end_date, provider=None)`.
- Produces: `CanonicalResearchService` calendar scope of `now.date() - 14 days` through `now.date() + 30 days`.
- Consumes: actual OpenBB fields `report_date`, `eps_actual`, `eps_consensus`, `revenue_actual`, `revenue_consensus`.

- [ ] **Step 1: Write failing exact-symbol and schema tests**

```python
def test_earnings_calendar_filters_exact_symbol_before_returning_rows():
    def earnings(**_):
        return FakeResult([
            FakeRow(symbol="AMD", report_date="2026-08-25", eps_consensus=1.2),
            FakeRow(symbol="NVDA", report_date="2026-08-27", eps_consensus=1.5),
        ], provider="fmp")
    result = _client(earnings=earnings).get_earnings_calendar(
        "NVDA", start_date="2026-08-06", end_date="2026-09-19", provider="fmp",
    )
    assert [row["symbol"] for row in result.data] == ["NVDA"]


def test_actual_fmp_earnings_fields_normalize():
    result = normalize_earnings(_raw("earnings_calendar", [{
        "symbol": "NVDA", "report_date": "2026-08-27",
        "eps_actual": None, "eps_consensus": 1.5,
        "revenue_actual": None, "revenue_consensus": 46_000_000_000,
        "last_updated": "2026-08-20",
    }], provider="fmp"), ASSET, now=NOW)
    assert result.observations[0].earnings_date.date() == date(2026, 8, 27)
    assert result.observations[0].estimated_eps == Decimal("1.5")
```

- [ ] **Step 2: Write a failing service-scope test**

```python
def test_asset_price_timeframe_is_not_forwarded_to_earnings_calendar():
    client = FakeResearchClient()
    client.earnings_calls = []
    service = CanonicalResearchService(client)
    service.get_asset_research_data(
        "NVDA", sections=("earnings",), start_date="2025-08-20",
        end_date="2026-08-20", now=NOW,
    )
    assert client.earnings_calls == [("NVDA", date(2026, 8, 2), date(2026, 9, 15))]
```

Add this fixture method before running the test:

```python
def get_earnings_calendar(self, symbol, *, start_date=None, end_date=None, provider=None):
    self.earnings_calls.append((symbol, start_date, end_date))
    return _raw(
        "earnings_calendar",
        [{"symbol": symbol, "report_date": "2026-08-27", "eps_consensus": 1.5}],
        provider=provider or "fmp",
        symbol=symbol,
        start_date=str(start_date),
        end_date=str(end_date),
    )
```

- [ ] **Step 3: Run the focused tests and confirm failures**

Run: `.venv/bin/pytest tests/trading/test_openbb_client.py tests/trading/test_canonical_research.py tests/trading/test_research_orchestration.py -k "earnings" -v`

Expected: FAIL because the client has no symbol, the normalizer reads old field
names, and the service forwards the one-year price range.

- [ ] **Step 4: Filter at the adapter boundary and map no match to scoped empty**

```python
result = self._execute(...)
matches = tuple(row for row in result.data if str(row.get("symbol") or "").upper() == symbol.upper())
return replace(
    result,
    symbol=symbol.upper(),
    data=matches,
    warnings=result.warnings + (() if matches else ("No earnings event was found in the current 44-day window.",)),
)
```

Permit `ResearchData.data == ()` for this post-filtered calendar result; do not
attach the global rows. `normalize_earnings` returns `QualityStatus.EMPTY` and
`Availability.MISSING` when no matching rows remain.

- [ ] **Step 5: Give earnings its independent service window**

```python
anchor = (now or datetime.now(timezone.utc)).date()
earnings_start = anchor - timedelta(days=14)
earnings_end = anchor + timedelta(days=30)
raw = self._fetch(
    symbol, "earnings_calendar", provider,
    (("start_date", earnings_start.isoformat()), ("end_date", earnings_end.isoformat())),
    lambda: self._client.get_earnings_calendar(
        symbol, start_date=earnings_start, end_date=earnings_end, provider=provider,
    ),
    refresh=refresh, allow_stale=allow_stale,
)
```

- [ ] **Step 6: Run earnings, relevance, report, and orchestration tests**

Run: `.venv/bin/pytest tests/trading -k "earnings or asset_report or orchestration" -v`

Expected: PASS; no report warning contains an FMP subscription URL.

- [ ] **Step 7: Commit bounded earnings**

```bash
git add app/trading/research/openbb_client.py app/trading/research/normalizers.py app/trading/research/service.py app/trading/research/orchestration.py tests/trading/test_openbb_client.py tests/trading/test_canonical_research.py tests/trading/test_research_orchestration.py
git commit -m "fix(research): scope earnings by asset and entitlement"
```

---

### Task 5: SEC filings and directly attributable news

**Files:**
- Modify: `app/trading/research/canonical.py`
- Modify: `app/trading/research/openbb_client.py`
- Modify: `app/trading/research/normalizers.py`
- Modify: `app/trading/research/service.py`
- Modify: `app/trading/research/freshness.py`
- Modify: `app/trading/research/__init__.py`
- Modify: `tests/trading/test_openbb_client.py`
- Modify: `tests/trading/test_canonical_research.py`

**Interfaces:**
- Produces: `CompanyFiling` and `CompanyFilings`.
- Produces: `get_company_filings(symbol, limit=12, provider=None)`.
- Produces: `normalize_filings(raw, asset, ...) -> CompanyFilings`.
- Produces: `filter_company_news(raw, asset) -> ResearchData` before `normalize_company_news`.
- Produces: `AssetResearchData.filings` and section literal `filings`.

- [ ] **Step 1: Write failing filing and news-relevance tests**

```python
def test_sec_filings_keep_bounded_official_metadata():
    raw = _raw("company_filings", [{
        "report_type": "10-Q", "filing_date": "2026-05-21",
        "report_date": "2026-04-30", "primary_doc_description": "Quarterly report",
        "accession_number": "0001045810-26-000123",
        "report_url": "https://www.sec.gov/Archives/example.htm",
    }], provider="sec")
    filings = normalize_filings(raw, ASSET, now=NOW)
    assert filings.items[0].form_type == "10-Q"
    assert filings.items[0].url.startswith("https://www.sec.gov/")


def test_company_news_keeps_only_direct_company_mentions():
    raw = _raw("company_news", [
        {"date": "2026-08-20T12:00:00+00:00", "title": "Nvidia earnings approach", "summary": "NVDA demand remains in focus"},
        {"date": "2026-08-20T11:00:00+00:00", "title": "Why Lockheed Martin fell", "summary": "A defense-sector update"},
    ], provider="yfinance")
    filtered = filter_company_news(raw, AssetIdentity("NVDA", CanonicalAssetType.EQUITY, name="NVIDIA Corporation"))
    assert [row["title"] for row in filtered.data] == ["Nvidia earnings approach"]
```

- [ ] **Step 2: Run focused tests and confirm failures**

Run: `.venv/bin/pytest tests/trading/test_openbb_client.py tests/trading/test_canonical_research.py -k "filing or directly or company_news" -v`

Expected: FAIL because filing types/routes and deterministic news filtering do not exist.

- [ ] **Step 3: Add canonical filing models and OpenBB route**

```python
@dataclass(frozen=True, slots=True)
class CompanyFiling:
    form_type: str
    filing_date: datetime
    report_date: datetime | None
    description: str | None
    accession_number: str | None
    url: str


@dataclass(frozen=True, slots=True)
class CompanyFilings:
    asset: AssetIdentity
    items: tuple[CompanyFiling, ...]
    provenance: ResearchProvenance
    as_of: datetime | None
    freshness: FreshnessStatus
    quality: DataQuality
```

```python
def get_company_filings(self, symbol: str, *, limit: int = 12, provider: str | None = None) -> ResearchData:
    providers = (provider,) if provider else self._provider_settings.filings
    return _first_available(providers, lambda selected: self._execute(
        lambda: self._obb.equity.fundamental.filings(symbol=symbol, limit=limit, provider=selected),
        symbol=symbol, asset_type="equity", category="company_filings",
        requested_provider=selected,
    ))
```

Normalize only `10-K`, `10-Q`, and `8-K`, newest first, with a maximum of five
report items. Reject non-HTTP(S) URLs and keep official provider URLs as
evidence links.

- [ ] **Step 4: Implement conservative news filtering and fallback field aliases**

```python
_COMPANY_SUFFIXES = {"inc", "incorporated", "corp", "corporation", "company", "limited", "ltd", "plc"}

def filter_company_news(raw: ResearchData, asset: AssetIdentity) -> ResearchData:
    tokens = {asset.symbol.lower()}
    tokens.update(
        token.lower() for token in re.findall(r"[A-Za-z0-9]+", asset.name or "")
        if len(token) >= 4 and token.lower() not in _COMPANY_SUFFIXES
    )
    rows = tuple(row for row in raw.data if any(
        re.search(rf"\b{re.escape(token)}\b", " ".join(str(row.get(key) or "") for key in ("title", "excerpt", "summary", "text")).lower())
        for token in tokens
    ))[:3]
    return replace(raw, data=rows)
```

Use `summary` or `text` as excerpt aliases in `normalize_company_news`. An empty
filtered result is `Availability.MISSING`, not a provider error.

- [ ] **Step 5: Fetch filings and filter news after profile identity resolution**

Add `filings` to `_VALID_SECTIONS`, equity-only validation, service aggregation,
quality, sources, cache TTLs, and exports. Call `filter_company_news(raw, asset)`
immediately before `normalize_company_news` so the richer FMP/Yahoo identity is
available.

- [ ] **Step 6: Run canonical, adapter, report, and orchestration suites**

Run: `.venv/bin/pytest tests/trading -v`

Expected: PASS.

- [ ] **Step 7: Commit filings and news relevance**

```bash
git add app/trading/research/canonical.py app/trading/research/openbb_client.py app/trading/research/normalizers.py app/trading/research/service.py app/trading/research/freshness.py app/trading/research/__init__.py tests/trading/test_openbb_client.py tests/trading/test_canonical_research.py
git commit -m "feat(research): add filings and direct news evidence"
```

---

### Task 6: Interpretable macro context

**Files:**
- Modify: `app/trading/research/openbb_client.py:365-410`
- Modify: `app/trading/research/service.py:180-200`
- Modify: `app/trading/research/jarvis_tools.py:35-65`
- Modify: `app/trading/research/normalizers.py:380-430`
- Modify: `tests/trading/test_openbb_client.py`
- Modify: `tests/trading/test_macro_context.py`
- Modify: `tests/test_macro_context_endpoint.py`

**Interfaces:**
- Produces: `MacroContextSpec(key, series_id, transform, unit, frequency)`.
- Extends: `get_macro_series(..., transform=None, unit=None)`.
- Produces: `/api/research/macro` series keys `inflation`, `unemployment`, `policy_rate`, `treasury_10y`, `real_gdp_growth`.

- [ ] **Step 1: Write failing macro specification tests**

```python
def test_macro_context_requests_interpretable_fred_series():
    service = FakeMacroService()
    payload = macro_context_payload(service)
    assert service.calls == [
        ("inflation", "CPIAUCSL", "pc1", "% YoY"),
        ("unemployment", "UNRATE", None, "%"),
        ("policy_rate", "FEDFUNDS", None, "%"),
        ("treasury_10y", "DGS10", None, "%"),
        ("real_gdp_growth", "GDPC1", "pc1", "% YoY"),
    ]
    assert payload["failures"] == []
```

```python
def test_fred_transform_and_unit_are_preserved():
    result = _client(fred_series=lambda **kwargs: FakeResult([
        FakeRow(date="2026-07-01", CPIAUCSL=2.7)
    ], provider="fred")).get_macro_series(
        "inflation", series_id="CPIAUCSL", transform="pc1", unit="% YoY", provider="fred",
    )
    assert result.data[0]["value"] == 2.7
    assert result.data[0]["unit"] == "% YoY"
```

- [ ] **Step 2: Run macro tests and confirm failure**

Run: `.venv/bin/pytest tests/trading/test_openbb_client.py tests/trading/test_macro_context.py tests/test_macro_context_endpoint.py -k "macro or fred" -v`

Expected: FAIL because transform, unit, and the five series specs do not exist.

- [ ] **Step 3: Add explicit macro specs and route parameters**

```python
@dataclass(frozen=True, slots=True)
class MacroContextSpec:
    key: str
    series_id: str
    transform: str | None
    unit: str
    frequency: str | None = None


MACRO_CONTEXT = (
    MacroContextSpec("inflation", "CPIAUCSL", "pc1", "% YoY"),
    MacroContextSpec("unemployment", "UNRATE", None, "%"),
    MacroContextSpec("policy_rate", "FEDFUNDS", None, "%"),
    MacroContextSpec("treasury_10y", "DGS10", None, "%"),
    MacroContextSpec("real_gdp_growth", "GDPC1", "pc1", "% YoY"),
)

ECONDB_EQUIVALENTS = {
    "inflation": ("INFLATION", "month", "% YoY"),
    "unemployment": ("UNEMPLOYMENT", "month", "%"),
    "policy_rate": ("INTEREST_RATE", "month", "%"),
}
```

Forward `transform` only to FRED. Put `unit` into returned raw rows before
normalization and preserve `(series_id, transform)` in provenance parameters.
Fallback to EconDB only for the three keys in `ECONDB_EQUIVALENTS`; the 10-year
Treasury yield and real-GDP growth remain explicitly unavailable when FRED is
unavailable rather than being replaced with a different concept.

- [ ] **Step 4: Return stable failure codes and public messages from the endpoint**

```python
failures.append({
    "indicator": spec.key,
    "code": getattr(exc, "code", "normalization_error"),
    "message": getattr(exc, "public_message", "Macro data is unavailable."),
    "provider": getattr(exc, "provider", None),
})
```

- [ ] **Step 5: Run macro and endpoint suites**

Run: `.venv/bin/pytest tests/trading/test_macro_context.py tests/test_macro_context_endpoint.py tests/trading/test_openbb_client.py -v`

Expected: PASS.

- [ ] **Step 6: Commit macro context**

```bash
git add app/trading/research/openbb_client.py app/trading/research/service.py app/trading/research/jarvis_tools.py app/trading/research/normalizers.py tests/trading/test_openbb_client.py tests/trading/test_macro_context.py tests/test_macro_context_endpoint.py
git commit -m "feat(research): add interpretable macro context"
```

---

### Task 7: Planner, reports, provider state, and HTTP contracts

**Files:**
- Modify: `app/trading/research/orchestration.py:215-410`
- Modify: `app/trading/research/reports.py:80-170`
- Modify: `app/trading/research/report_service.py:35-260`
- Modify: `app/trading/research/provider_status.py:1-75`
- Modify: `app/trading/research/jarvis_tools.py:100-145`
- Modify: `app/models.py:55-95`
- Modify: `app/main.py:295-335`
- Modify: `tests/trading/fixtures.py`
- Modify: `tests/trading/test_research_orchestration.py`
- Modify: `tests/trading/test_asset_research_reports.py`
- Create: `tests/trading/test_jarvis_tools.py`
- Modify: `tests/trading/test_provider_status.py`
- Modify: `tests/test_research_run_endpoint.py`
- Modify: `tests/test_research_payload_response.py`

**Interfaces:**
- Consumes: canonical `quote`, `valuation`, `filings`, `earnings`, and provider attempts.
- Produces: report sections `snapshot`, `valuation`, `fundamentals`, `earnings`, `estimates`, `filings`.
- Produces: report sources with canonical provider attempts and coverage with stable section failures.
- Produces: provider states `built_in`, `configured`, `not_configured`; optional `last_result` stays non-secret.
- Preserves: `ChatResponse.research_payload` and `/api/research/run` route shape.

- [ ] **Step 1: Write failing planner and report-contract tests**

```python
def test_asset_plan_requests_every_essential_equity_section():
    plan = ResearchPlanner().plan(ResearchRequest(ResearchIntent.ASSET_ANALYSIS, ("NVDA",), timeframe="1y"))
    assert plan.sections == (
        "quote", "prices", "profile", "fundamentals", "valuation",
        "earnings", "estimates", "filings", "news",
    )


def test_report_exposes_snapshot_and_recent_filings():
    report = _build(equity_full_evidence_case())
    sections = {section.key: section for section in report.sections}
    assert dict((item.key, item.value) for item in sections["snapshot"].metrics)["last_price"] == Decimal("216.61")
    assert report.filings[0].form_type == "10-Q"
```

Add the fixture in `tests/trading/fixtures.py`:

```python
def equity_full_evidence_case() -> AssetResearchData:
    base = equity_growth_case()
    quote = EquityQuote(
        asset=base.asset,
        last_price=Decimal("216.61"), previous_close=Decimal("214.40"),
        open=None, high=None, low=None, volume=None,
        year_high=Decimal("225"), year_low=Decimal("86"),
        moving_average_50d=None, moving_average_200d=None, currency="USD",
        provenance=_provenance("equity_quote"), as_of=NOW,
        freshness=FreshnessStatus.FRESH,
        quality=DataQuality(QualityStatus.COMPLETE),
    )
    valuation = ValuationData(
        base.asset,
        (("market_cap", Decimal("5250000000000")), ("pe_ratio", Decimal("31.8"))),
        _provenance("fundamental_metrics"), NOW, FreshnessStatus.FRESH,
        DataQuality(QualityStatus.COMPLETE),
    )
    filings = CompanyFilings(
        base.asset,
        (CompanyFiling("10-Q", NOW, NOW, "Quarterly report", "fixture-accession", "https://www.sec.gov/Archives/example.htm"),),
        _provenance("company_filings"), NOW, FreshnessStatus.FRESH,
        DataQuality(QualityStatus.COMPLETE),
    )
    return replace(base, quote=quote, valuation=valuation, filings=filings)
```

- [ ] **Step 2: Write failing safe wording and provider-state tests**

```python
def test_response_wording_never_contains_raw_provider_exception():
    request = ResearchRequest(ResearchIntent.ASSET_ANALYSIS, ("NVDA",))
    response = ResearchResponse(
        request=request,
        status=RequestStatus.FAILED,
        assets=(),
        plan=None,
        warnings=("Earnings data is unavailable in the configured tier.",),
    )
    text = render_research_response(response)
    assert "subscription page" not in text
    assert "https://" not in text
    assert "Earnings data is unavailable in the configured tier." in text


def test_provider_status_distinguishes_configuration_from_liveness():
    statuses = {item.provider: item for item in provider_statuses({"FMP_API_KEY": "configured"})}
    assert statuses["yfinance"].configuration_state == "built_in"
    assert statuses["fmp"].configuration_state == "configured"
    assert not hasattr(statuses["fmp"], "availability")
```

- [ ] **Step 3: Run focused orchestration/report/API tests**

Run: `.venv/bin/pytest tests/trading/test_research_orchestration.py tests/trading/test_asset_research_reports.py tests/trading/test_jarvis_tools.py tests/trading/test_provider_status.py tests/test_research_run_endpoint.py tests/test_research_payload_response.py -v`

Expected: FAIL because new sections and configuration-state vocabulary do not exist.

- [ ] **Step 4: Extend planner and report contracts**

Add the essential equity section tuple shown in Step 1. Crypto asset reports
continue to request only `("crypto",)`. Add
`filings: tuple[CompanyFiling, ...] = ()` to `AssetResearchReport`. Build the
snapshot from `data.quote`, fall back to the latest price bar only when quote is
missing, and include valuation/fundamental/earnings/estimate/filing sections
only when observed canonical values exist.

```python
if data.quote is not None:
    metrics = tuple(
        ReportMetric(key, value, unit=data.quote.currency if key in {"last_price", "previous_close"} else None)
        for key, value in (
            ("last_price", data.quote.last_price),
            ("previous_close", data.quote.previous_close),
            ("year_high", data.quote.year_high),
            ("year_low", data.quote.year_low),
        ) if value is not None
    )
    sections["snapshot"] = ReportSection("snapshot", "Market snapshot", metrics=metrics, provenance=(data.quote.provenance,))
```

Extend report sources and coverage without copying raw provider exception text:

```python
@dataclass(frozen=True, slots=True)
class ReportSource:
    provider: str | None
    source_category: str
    retrieved_at: datetime
    attempts: tuple[ProviderAttempt, ...] = ()


@dataclass(frozen=True, slots=True)
class ReportDataCoverage:
    section: str
    availability: Availability
    freshness: FreshnessStatus
    missing_fields: tuple[str, ...] = ()
    failures: tuple[SectionFailure, ...] = ()
```

Map each section's successful `ResearchProvenance.attempts` into its
`ReportSource`. Map only matching canonical `SectionFailure` records into the
coverage row for that section.

- [ ] **Step 5: Replace readiness claims with configuration state**

```python
@dataclass(frozen=True, slots=True)
class ProviderStatus:
    provider: str
    credential_configured: bool
    configuration_state: Literal["built_in", "configured", "not_configured"]
    current_coverage: tuple[str, ...]
    last_result: dict[str, str] | None = None
```

Do not make network calls from the status endpoint. If a process-local last
attempt registry is added, update it only after real research requests and
store provider, outcome, code, and UTC timestamp; never store exception text or
request parameters.

- [ ] **Step 6: Use stable messages in rendered and HTTP responses**

Render one concise report status plus section names. Preserve detailed codes and
coverage in `research_payload`. Ensure `ResearchRunRequest` does not accept
provider input. Add API assertions that serialized payloads contain no
credential strings, provider plan URLs, or raw 402 prose.

At the service boundary, construct failures with safe public copy:

```python
@staticmethod
def _failure(section: str, exc: Exception) -> SectionFailure:
    return SectionFailure(
        section=section,
        code=getattr(exc, "code", "normalization_error"),
        message=getattr(exc, "public_message", "This research section is unavailable."),
        provider=getattr(exc, "provider", None),
    )
```

- [ ] **Step 7: Run all focused backend tests**

Run: `.venv/bin/pytest tests/trading tests/test_macro_context_endpoint.py tests/test_research_run_endpoint.py tests/test_research_payload_response.py -v`

Expected: PASS.

- [ ] **Step 8: Commit integration contracts**

```bash
git add app/trading/research/orchestration.py app/trading/research/reports.py app/trading/research/report_service.py app/trading/research/provider_status.py app/trading/research/jarvis_tools.py app/models.py app/main.py tests/trading/fixtures.py tests/trading/test_research_orchestration.py tests/trading/test_asset_research_reports.py tests/trading/test_jarvis_tools.py tests/trading/test_provider_status.py tests/test_research_run_endpoint.py tests/test_research_payload_response.py
git commit -m "feat(research): expose essential evidence contracts"
```

---

### Task 8: Backend documentation and verification gate

**Files:**
- Modify: `docs/openbb-research.md`
- Modify: `docs/canonical-research-data.md`
- Modify: `docs/asset-research-reports.md`
- Modify: `docs/natural-language-quant-research.md`
- Modify: `architecture.md`
- Modify: `scripts/openbb_research_probe.py`
- Test: full repository test suite

**Interfaces:**
- Consumes: all completed backend contracts.
- Produces: credential-free architecture/provider documentation and a safe opt-in live probe.

- [ ] **Step 1: Update the safe live probe to print coverage only**

```python
def summarize(label: str, result: ResearchData) -> None:
    fields = sorted({key for row in result.data[:3] for key, value in row.items() if value is not None})
    attempts = ",".join(f"{item.provider}:{item.outcome}" for item in result.attempts)
    print(f"{label}|provider={result.provider}|rows={len(result.data)}|fields={','.join(fields)}|attempts={attempts}")
```

The probe calls bounded NVDA price, quote, profile, statements, metrics,
estimates, earnings, filings, direct news, the five macro series, and BTC/ETH
price history. It never prints raw values, URLs, headers, settings, or exception
strings; failures print only exception type, stable code, and provider.

- [ ] **Step 2: Update the research documentation**

Document the exact provider table, fallback semantics, canonical quote/filing
models, 44-day earnings scope, direct-mention news filter, five macro series,
configuration-state vocabulary, and explicit free-tier limitations. Remove the
claim that Benzinga is active merely because its key exists.

- [ ] **Step 3: Run documentation and diff checks**

Run: `git diff --check`

Expected: exit 0 with no whitespace errors.

Run: `rg -n "6 active|Premium Query Parameter|subscription page|provider-neutral estimates endpoint" app docs tests`

Expected: no user-facing stale copy; test fixtures may contain stable synthetic
error markers only when asserting sanitization.

- [ ] **Step 4: Run JavaScript parsing before the UI plan starts**

Run: `.venv/bin/python - <<'PY'
from pathlib import Path
import re, subprocess, tempfile
html = Path("app/static/index.html").read_text()
scripts = re.findall(r"<script>(.*?)</script>", html, re.S)
with tempfile.NamedTemporaryFile("w", suffix=".js") as handle:
    handle.write("\n".join(scripts))
    handle.flush()
    subprocess.run(["node", "--check", handle.name], check=True)
PY`

Expected: exit 0.

- [ ] **Step 5: Run the full credential-free test suite**

Run: `.venv/bin/pytest -q`

Expected: all tests pass; no network credential is required.

- [ ] **Step 6: Run the opt-in live provider probe**

Run: `env SSL_CERT_FILE="$(.venv/bin/python -c 'import certifi; print(certifi.where())')" .venv/bin/python scripts/openbb_research_probe.py`

Expected: successful bounded coverage for Yahoo Finance, FMP, SEC, Tiingo,
FRED, and BTC/ETH routes that are configured; entitlement or empty results are
reported as stable codes with no secrets. This check is observational and does
not replace fixtures.

- [ ] **Step 7: Commit backend docs and probe**

```bash
git add docs/openbb-research.md docs/canonical-research-data.md docs/asset-research-reports.md docs/natural-language-quant-research.md architecture.md scripts/openbb_research_probe.py
git commit -m "docs: document free-tier research coverage"
```
