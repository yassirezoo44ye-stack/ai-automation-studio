"""Deterministic paper-trading simulator. No brokerage connections or real orders."""
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

Side = Literal["buy", "sell"]


@dataclass
class PaperPortfolio:
    cash: Decimal = Decimal("10000")
    holdings: dict[str, Decimal] = field(default_factory=dict)
    ledger: list[dict[str, str]] = field(default_factory=list)

    def execute(self, symbol: str, side: Side, quantity: Decimal, price: Decimal) -> dict[str, str]:
        """Apply a virtual fill; reject invalid orders without mutating state."""
        if not symbol or not symbol.isascii() or not all(c.isalnum() or c in ".-_" for c in symbol):
            raise ValueError("Invalid symbol")
        if side not in ("buy", "sell") or not quantity.is_finite() or not price.is_finite():
            raise ValueError("Invalid order")
        if quantity <= 0 or price <= 0:
            raise ValueError("Quantity and price must be positive")
        value = quantity * price
        current = self.holdings.get(symbol, Decimal("0"))
        if side == "buy" and value > self.cash:
            raise ValueError("Insufficient virtual cash")
        if side == "sell" and quantity > current:
            raise ValueError("Insufficient virtual holdings")
        self.cash += -value if side == "buy" else value
        updated = current + quantity if side == "buy" else current - quantity
        if updated:
            self.holdings[symbol] = updated
        else:
            self.holdings.pop(symbol, None)
        fill = {"symbol": symbol, "side": side, "quantity": str(quantity), "price": str(price), "notional": str(value), "mode": "paper"}
        self.ledger.append(fill)
        return fill

    def equity(self, marks: dict[str, Decimal]) -> Decimal:
        if any(symbol not in marks or not marks[symbol].is_finite() or marks[symbol] < 0 for symbol in self.holdings):
            raise ValueError("Valid market marks required for every holding")
        return self.cash + sum((quantity * marks[symbol] for symbol, quantity in self.holdings.items()), Decimal("0"))
