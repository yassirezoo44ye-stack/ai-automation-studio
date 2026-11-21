import pytest
from app.ai.credential_checkpoint import mark_scope, plan_next_scopes

def test_deterministic_pending_and_interrupted_work():
    assert plan_next_scopes({"b", "a", "c"}, {"a": "running", "b": "verified"}, limit=2) == ["a", "c"]

def test_failed_requires_manual_reset():
    assert plan_next_scopes({"a", "b"}, {"a": "failed", "b": "pending"}) == ["b"]
    assert mark_scope({"a": "failed"}, "a", "pending") == {"a": "pending"}

def test_checkpoint_transition_and_immutability():
    original = {"a": "pending"}
    running = mark_scope(original, "a", "running")
    assert original == {"a": "pending"}
    assert mark_scope(running, "a", "verified") == {"a": "verified"}
    with pytest.raises(ValueError):
        mark_scope({"a": "verified"}, "a", "running")

@pytest.mark.parametrize("inventory,checkpoint", [
    (set(), {}),
    ({"a"}, {"b": "pending"}),
    ({"a"}, {"a": "unknown"}),
])
def test_bad_inventory_or_checkpoint_rejected(inventory, checkpoint):
    with pytest.raises(ValueError):
        plan_next_scopes(inventory, checkpoint)

@pytest.mark.parametrize("limit", [0, 101, True])
def test_invalid_limits_rejected(limit):
    with pytest.raises(ValueError):
        plan_next_scopes({"a"}, {}, limit=limit)
