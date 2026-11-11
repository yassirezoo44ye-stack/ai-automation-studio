"""Isolated unit tests for simulation-only trading."""
from decimal import Decimal
import pytest

from app.market_intelligence.simulator import PaperPortfolio


def test_paper_buy_sell_and_equity():
    portfolio = PaperPortfolio()
    assert portfolio.execute("TEST", "buy", Decimal("2"), Decimal("100"))["mode"] == "paper"
    assert portfolio.cash == Decimal("9800")
    assert portfolio.equity({"TEST": Decimal("110")}) == Decimal("10020")
    portfolio.execute("TEST", "sell", Decimal("1"), Decimal("110"))
    assert portfolio.cash == Decimal("9910")
    assert portfolio.holdings["TEST"] == Decimal("1")


@pytest.mark.parametrize("side,quantity,price", [
    ("buy", Decimal("101"), Decimal("100")),
    ("sell", Decimal("1"), Decimal("100")),
    ("buy", Decimal("-1"), Decimal("100")),
    ("buy", Decimal("1"), Decimal("NaN")),
    ("buy", Decimal("1"), Decimal("0")),
])
def test_rejected_order_does_not_change_state(side, quantity, price):
    portfolio = PaperPortfolio()
    with pytest.raises(ValueError):
        portfolio.execute("TEST", side, quantity, price)
    assert portfolio.cash == Decimal("10000")
    assert portfolio.holdings == {}
    assert portfolio.ledger == []
