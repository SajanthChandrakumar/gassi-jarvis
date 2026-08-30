"""Deterministic trading and portfolio domain boundary.

Financial events and value objects live in ``app.trading.domain``. Future
subpackages may cover portfolio state, analytics, market data, backtesting,
risk, and strategies. Financial state and calculations must stay in
deterministic Python code; language-model output is never authoritative.
"""
