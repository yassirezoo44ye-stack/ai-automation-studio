"""Deterministic, offline research pipeline for historical paper simulations."""
from dataclasses import dataclass
from decimal import Decimal

from .backtest import sma_crossover_backtest
from .historical_data import parse_price_csv
from .reporting import SimulationReport, summarize_equity


@dataclass(frozen=True)
class ResearchResult:
    symbol: str
    observations: int
    trade_count: int
    report: SimulationReport
    assumptions: tuple[str, ...]


def run_research(
    csv_text: str,
    *,
    symbol: str = "DEMO",
    fast_window: int = 3,
    slow_window: int = 5,
    starting_cash: Decimal = Decimal("10000"),
    fee_bps: Decimal = Decimal("10"),
    slippage_bps: Decimal = Decimal("5"),
) -> ResearchResult:
    """Validate imported prices, backtest, and summarize a virtual account.

    This function has no persistence, network, brokerage, or live-trading side effects.
    """
    series = parse_price_csv(csv_text)
    result = sma_crossover_backtest(
        series.bars,
        symbol=symbol,
        fast_window=fast_window,
        slow_window=slow_window,
        starting_cash=starting_cash,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
    )
    report = summarize_equity(result.equity_curve, result.initial_cash)
    return ResearchResult(
        symbol=symbol,
        observations=len(series.bars),
        trade_count=len(result.trades),
        report=report,
        assumptions=(
            "Historical prices are supplied by the user and are not verified.",
            "Signals use completed bars and orders fill at the next opening price.",
            "Results are hypothetical and exclude dividends, splits, taxes and liquidity.",
            "No real orders or brokerage connections are made.",
        ),
    )
