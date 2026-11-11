"""Historical market data validation tests."""
import pytest
from app.market_intelligence.historical_data import parse_price_csv


def test_parse_valid_prices():
    data = "timestamp,open,close\n2026-01-01T00:00:00+00:00,100,101\n2026-01-02T00:00:00+00:00,101,99\n"
    series = parse_price_csv(data)
    assert len(series.bars) == 2
    assert str(series.bars[0].close) == "101"


@pytest.mark.parametrize("data", [
    "timestamp,open,close\n2026-01-01T00:00:00,1,2\n",
    "timestamp,open,close\n2026-01-01T00:00:00+00:00,NaN,2\n",
    "timestamp,open,close\n2026-01-01T00:00:00+00:00,0,2\n",
    "timestamp,open,close\n2026-01-02T00:00:00+00:00,1,2\n2026-01-01T00:00:00+00:00,2,3\n",
    "timestamp,open,close\n2026-01-01T00:00:00+00:00,1,2\n2026-01-01T00:00:00+00:00,2,3\n",
    "date,open,close\n2026-01-01,1,2\n",
    "timestamp,open,close\n",
])
def test_reject_bad_series(data):
    with pytest.raises(ValueError):
        parse_price_csv(data)
