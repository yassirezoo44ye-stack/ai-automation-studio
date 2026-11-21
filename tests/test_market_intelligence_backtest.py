"""Regression checks for deterministic, no-lookahead paper backtesting."""
from decimal import Decimal
import pytest

from app.market_intelligence.backtest import Bar, sma_crossover_backtest


def sample_bars():
    return [Bar(Decimal(x), Decimal(x)) for x in [10, 10, 10, 10, 10, 12, 14, 16, 9, 8, 7, 13, 15]]


def test_backtest_is_reproducible_and_bounded():
    first = sma_crossover_backtest(sample_bars())
    second = sma_crossover_backtest(sample_bars())
    assert first == second
    assert len(first.equity_curve) == len(sample_bars())
    assert first.max_drawdown_pct >= 0
    assert all(t["mode"] == "paper" for t in first.trades)


def test_invalid_input_rejected():
    with pytest.raises(ValueError):
        sma_crossover_backtest(sample_bars(), fast_window=5, slow_window=3)
    with pytest.raises(ValueError):
        sma_crossover_backtest(sample_bars(), fee_bps=Decimal("-1"))
    with pytest.raises(ValueError):
        sma_crossover_backtest(sample_bars()[:4])
    with pytest.raises(ValueError):
        Bar(Decimal("NaN"), Decimal("1"))


def test_future_bar_does_not_change_prior_equity():
    bars = sample_bars()
    before = sma_crossover_backtest(bars)
    altered = bars[:-1] + [Bar(Decimal("100"), Decimal("100"))]
    after = sma_crossover_backtest(altered)
    assert before.equity_curve[:-1] == after.equity_curve[:-1]
