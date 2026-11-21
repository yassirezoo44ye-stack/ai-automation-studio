"""End-to-end tests for the offline market research pipeline."""
from decimal import Decimal

import pytest

from app.market_intelligence.pipeline import run_research


def sample_csv():
    prices = [10, 10, 10, 10, 10, 12, 14, 16, 9, 8, 7, 13, 15]
    return "timestamp,open,close\n" + "".join(
        f"2026-01-{i:02d}T00:00:00+00:00,{price},{price}\n"
        for i, price in enumerate(prices, start=1)
    )


def test_full_research_pipeline_is_reproducible():
    first = run_research(sample_csv())
    second = run_research(sample_csv())
    assert first == second
    assert first.observations == 13
    assert first.report.observations == 13
    assert first.report.initial_equity == Decimal("10000")
    assert first.trade_count >= 1
    assert len(first.assumptions) == 4


def test_research_rejects_malformed_input():
    with pytest.raises(ValueError):
        run_research("timestamp,open,close\n2026-01-01T00:00:00,1,2\n")


def test_research_rejects_insufficient_data():
    with pytest.raises(ValueError):
        run_research("timestamp,open,close\n2026-01-01T00:00:00+00:00,1,2\n")
