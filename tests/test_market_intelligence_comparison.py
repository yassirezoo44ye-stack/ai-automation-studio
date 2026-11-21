"""Tests for side-by-side historical strategy research."""
import pytest

from app.market_intelligence.comparison import StrategyConfig, compare_strategies


def csv_data():
    values = [10, 10, 10, 10, 10, 12, 14, 16, 9, 8, 7, 13, 15]
    return "timestamp,open,close\n" + "".join(
        f"2026-01-{i:02d}T00:00:00+00:00,{v},{v}\n"
        for i, v in enumerate(values, 1)
    )


def test_comparison_preserves_order_and_same_observations():
    result = compare_strategies(
        csv_data(),
        [StrategyConfig("fast", 2, 4), StrategyConfig("slow", 3, 5)],
    )
    assert [x.name for x in result] == ["fast", "slow"]
    assert all(x.result.observations == 13 for x in result)


@pytest.mark.parametrize("strategies", [
    [],
    [StrategyConfig("same", 2, 4), StrategyConfig("same", 3, 5)],
    [StrategyConfig("", 2, 4)],
    [StrategyConfig("bad", 5, 3)],
    [StrategyConfig(str(i), 2, 4) for i in range(11)],
])
def test_comparison_rejects_invalid_inputs(strategies):
    with pytest.raises(ValueError):
        compare_strategies(csv_data(), strategies)
