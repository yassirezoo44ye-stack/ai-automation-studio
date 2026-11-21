"""Reproducible, long-only historical simulation; never connects to a broker.

Signals are derived from completed historical bars. Orders fill at the NEXT
bar's opening price, preventing same-bar lookahead. Results are illustrative.
"""
from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence

from .simulator import PaperPortfolio


@dataclass(frozen=True)
class Bar:
    open: Decimal
    close: Decimal

    def __post_init__(self):
        if any(not v.is_finite() or v <= 0 for v in (self.open, self.close)):
            raise ValueError("OHLC prices must be finite and positive")


@dataclass(frozen=True)
class BacktestResult:
    final_equity: Decimal
    initial_cash: Decimal
    total_return_pct: Decimal
    max_drawdown_pct: Decimal
    trades: tuple[dict[str, str], ...]
    equity_curve: tuple[Decimal, ...]


def sma_crossover_backtest(
    bars: Sequence[Bar],
    *,
    symbol: str = "DEMO",
    fast_window: int = 3,
    slow_window: int = 5,
    starting_cash: Decimal = Decimal("10000"),
    fee_bps: Decimal = Decimal("10"),
    slippage_bps: Decimal = Decimal("5"),
) -> BacktestResult:
    """Simulate an all-in long-only SMA cross using next-open fills.

    Bars must be in chronological order and from a consistent interval.
    Does not account for splits, dividends, financing, liquidity, or taxes.
    """
    if not 1 <= fast_window < slow_window:
        raise ValueError("Require 1 <= fast_window < slow_window")
    if not starting_cash.is_finite() or starting_cash <= 0:
        raise ValueError("Starting cash must be positive")
    if any(not x.is_finite() or x < 0 or x >= 10000 for x in (fee_bps, slippage_bps)):
        raise ValueError("Invalid fee or slippage bps")
    if len(bars) < slow_window + 2:
        raise ValueError("Insufficient bars")
    if len(bars) > 100000:
        raise ValueError("Too many bars")
    portfolio = PaperPortfolio(cash=starting_cash)
    equity_curve: list[Decimal] = []
    peak = starting_cash
    max_drawdown = Decimal("0")
    fee_rate = fee_bps / Decimal("10000")
    slip_rate = slippage_bps / Decimal("10000")
    closes = [bar.close for bar in bars]
    for i, bar in enumerate(bars):
        # Completed bars through i-1 only; fill at current opening.
        if i >= slow_window + 1:
            previous = closes[:i]
            fast = sum(previous[-fast_window:]) / fast_window
            slow = sum(previous[-slow_window:]) / slow_window
            prior_fast = sum(previous[-fast_window-1:-1]) / fast_window
            prior_slow = sum(previous[-slow_window-1:-1]) / slow_window
            if prior_fast <= prior_slow and fast > slow and symbol not in portfolio.holdings:
                execution_price = bar.open * (Decimal("1") + slip_rate)
                qty = portfolio.cash / (execution_price * (Decimal("1") + fee_rate))
                if qty > 0:
                    portfolio.execute(symbol, "buy", qty, execution_price)
                    portfolio.cash -= qty * execution_price * fee_rate
            elif prior_fast >= prior_slow and fast < slow and symbol in portfolio.holdings:
                execution_price = bar.open * (Decimal("1") - slip_rate)
                qty = portfolio.holdings[symbol]
                portfolio.execute(symbol, "sell", qty, execution_price)
                portfolio.cash -= qty * execution_price * fee_rate
        equity = portfolio.equity({symbol: bar.close})
        equity_curve.append(equity)
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, (peak - equity) / peak * 100)
    final = equity_curve[-1]
    return BacktestResult(
        final_equity=final,
        initial_cash=starting_cash,
        total_return_pct=(final / starting_cash - 1) * 100,
        max_drawdown_pct=max_drawdown,
        trades=tuple(portfolio.ledger),
        equity_curve=tuple(equity_curve),
    )
