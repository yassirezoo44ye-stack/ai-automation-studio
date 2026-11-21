"""Analytics tests for paper simulation reports."""
from decimal import Decimal
import pytest

from app.market_intelligence.reporting import summarize_equity


def test_report_counts_and_drawdown():
    report = summarize_equity(
        [Decimal("110"), Decimal("99"), Decimal("99"), Decimal("121")],
        Decimal("100"),
    )
    assert report.return_pct == Decimal("21")
    assert report.max_drawdown_pct == Decimal("10")
    assert (report.profitable_periods, report.losing_periods, report.flat_periods) == (2, 1, 1)
    assert report.observations == 4


def test_complete_virtual_loss():
    report = summarize_equity([Decimal("0")], Decimal("100"))
    assert report.max_drawdown_pct == Decimal("100")
    assert report.return_pct == Decimal("-100")


@pytest.mark.parametrize("curve,initial", [
    ([], Decimal("100")),
    ([Decimal("1")], Decimal("0")),
    ([Decimal("-1")], Decimal("100")),
    ([Decimal("NaN")], Decimal("100")),
    ([Decimal("1")], Decimal("Infinity")),
])
def test_invalid_equity_data_rejected(curve, initial):
    with pytest.raises(ValueError):
        summarize_equity(curve, initial)
