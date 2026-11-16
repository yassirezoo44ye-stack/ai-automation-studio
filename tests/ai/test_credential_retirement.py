import pytest
from app.ai import credential_retirement as retirement

@pytest.mark.asyncio
@pytest.mark.parametrize("counts,eligible", [
    ({"expected": 3, "enrolled": 3, "verified": 3}, True),
    ({"expected": 3, "enrolled": 2, "verified": 2}, False),
    ({"expected": 3, "enrolled": 3, "verified": 2}, False),
    ({"expected": 0, "enrolled": 0, "verified": 0}, False),
])
async def test_retirement_preflight_requires_complete_coverage(monkeypatch, counts, eligible):
    async def coverage(conn): return counts
    monkeypatch.setattr(retirement, "read_rotation_coverage", coverage)
    assert (await retirement.retirement_preflight(object()))["eligible_for_final_audit"] is eligible

@pytest.mark.asyncio
@pytest.mark.parametrize("counts", [
    {"expected": 1, "enrolled": 2, "verified": 2},
    {"expected": 1, "enrolled": 1, "verified": 2},
    {"expected": True, "enrolled": 1, "verified": 1},
    {"expected": -1, "enrolled": 0, "verified": 0},
])
async def test_retirement_preflight_rejects_inconsistent_counts(monkeypatch, counts):
    async def coverage(conn): return counts
    monkeypatch.setattr(retirement, "read_rotation_coverage", coverage)
    with pytest.raises(ValueError):
        await retirement.retirement_preflight(object())
