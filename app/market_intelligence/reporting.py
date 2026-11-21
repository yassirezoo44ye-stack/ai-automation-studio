"""Read-only analytics for simulated historical equity curves."""
from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence


@dataclass(frozen=True)
class SimulationReport:
    initial_equity: Decimal
    final_equity: Decimal
    return_pct: Decimal
    max_drawdown_pct: Decimal
    profitable_periods: int
    losing_periods: int
    flat_periods: int
    observations: int


def summarize_equity(curve: Sequence[Decimal], initial_equity: Decimal) -> SimulationReport:
    """Summarize a virtual portfolio without suggesting real trades.

    The initial equity is the baseline before the first observation. Period
    changes are calculated against that baseline and successive observations.
    """
    if not initial_equity.is_finite() or initial_equity <= 0:
        raise ValueError("Initial equity must be finite and positive")
    if not curve or len(curve) > 100000:
        raise ValueError("Equity curve length must be between 1 and 100000")
    if any(not value.is_finite() or value < 0 for value in curve):
        raise ValueError("Equity values must be finite and nonnegative")

    peak = initial_equity
    worst = Decimal("0")
    positive = negative = flat = 0
    previous = initial_equity
    for equity in curve:
        if equity > previous:
            positive += 1
        elif equity < previous:
            negative += 1
        else:
            flat += 1
        peak = max(peak, equity)
        worst = max(worst, (peak - equity) / peak * Decimal("100"))
        previous = equity

    return SimulationReport(
        initial_equity=initial_equity,
        final_equity=curve[-1],
        return_pct=(curve[-1] / initial_equity - Decimal("1")) * Decimal("100"),
        max_drawdown_pct=worst,
        profitable_periods=positive,
        losing_periods=negative,
        flat_periods=flat,
        observations=len(curve),
    )
