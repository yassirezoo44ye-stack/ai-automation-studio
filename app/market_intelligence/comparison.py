"""Side-by-side comparison of educational historical simulations."""
from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence

from .pipeline import ResearchResult, run_research


@dataclass(frozen=True)
class StrategyConfig:
    name: str
    fast_window: int
    slow_window: int


@dataclass(frozen=True)
class StrategyComparison:
    name: str
    result: ResearchResult


def compare_strategies(
    csv_text: str,
    strategies: Sequence[StrategyConfig],
    *,
    starting_cash: Decimal = Decimal("10000"),
    fee_bps: Decimal = Decimal("10"),
    slippage_bps: Decimal = Decimal("5"),
) -> tuple[StrategyComparison, ...]:
    """Compare up to 10 predefined strategies on identical user-supplied data.

    Returns the input order, without ranking or recommending investments.
    No network calls, real trading, or data persistence occur.
    """
    if not 1 <= len(strategies) <= 10:
        raise ValueError("Provide between one and ten strategies")
    if len({s.name for s in strategies}) != len(strategies):
        raise ValueError("Strategy names must be unique")
    if any(not s.name.strip() or len(s.name) > 80 for s in strategies):
        raise ValueError("Invalid strategy name")
    return tuple(
        StrategyComparison(
            name=strategy.name,
            result=run_research(
                csv_text,
                fast_window=strategy.fast_window,
                slow_window=strategy.slow_window,
                starting_cash=starting_cash,
                fee_bps=fee_bps,
                slippage_bps=slippage_bps,
            ),
        )
        for strategy in strategies
    )
