"""Strict historical CSV ingestion for research-only paper simulations."""
import csv
import io
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation

from .backtest import Bar

MAX_BYTES = 2_000_000
MAX_ROWS = 100_000


@dataclass(frozen=True)
class HistoricalSeries:
    timestamps: tuple[datetime, ...]
    bars: tuple[Bar, ...]


def parse_price_csv(content: str) -> HistoricalSeries:
    """Parse timestamp,open,close rows in ascending ISO-8601 timestamp order.

    Input must be a UTF-8 text string with a header; timezone offsets are
    mandatory to prevent ambiguous chronology. No network access occurs.
    """
    if len(content.encode("utf-8")) > MAX_BYTES:
        raise ValueError("CSV exceeds size limit")
    reader = csv.DictReader(io.StringIO(content, newline=""))
    if reader.fieldnames != ["timestamp", "open", "close"]:
        raise ValueError("Expected CSV header: timestamp,open,close")
    stamps: list[datetime] = []
    bars: list[Bar] = []
    previous: datetime | None = None
    for row in reader:
        if len(bars) >= MAX_ROWS:
            raise ValueError("Too many price rows")
        if None in row or any(row.get(k) is None for k in reader.fieldnames):
            raise ValueError("Malformed price row")
        try:
            stamp = datetime.fromisoformat(row["timestamp"].strip())
            if stamp.tzinfo is None or stamp.utcoffset() is None:
                raise ValueError("Timestamp must include timezone")
            opening = Decimal(row["open"].strip())
            closing = Decimal(row["close"].strip())
            bar = Bar(opening, closing)
        except (InvalidOperation, TypeError) as exc:
            raise ValueError("Invalid numeric value") from exc
        if previous is not None and stamp <= previous:
            raise ValueError("Timestamps must be strictly increasing")
        stamps.append(stamp)
        bars.append(bar)
        previous = stamp
    if not bars:
        raise ValueError("No price rows")
    return HistoricalSeries(tuple(stamps), tuple(bars))
