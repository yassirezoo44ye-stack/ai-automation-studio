import pytest
from app.ai.credential_audit import summarize_rotation_audit

def result(scanned=1, not_primary=0, unreadable=0, complete=True):
    return dict(scanned=scanned, not_primary=not_primary, unreadable=unreadable, complete=complete)

def test_all_expected_scopes_verified():
    assert summarize_rotation_audit({'a': result(), 'b': result()}, expected_scope_ids={'a', 'b'}) == {
        "expected_scopes": 2, "checked_scopes": 2, "scanned": 2,
        "not_primary": 0, "unreadable": 0, "complete": True
    }

def test_missing_scope_blocks_completion():
    assert not summarize_rotation_audit({'a': result()}, expected_scope_ids={'a', 'b'})["complete"]

def test_unreadable_and_old_keys_block_completion():
    assert not summarize_rotation_audit({'a': result(not_primary=1, unreadable=1, complete=False)}, expected_scope_ids={'a'})["complete"]

@pytest.mark.parametrize("bad", [
    {"scanned": 1, "not_primary": 2, "unreadable": 0, "complete": False},
    {"scanned": 1, "not_primary": 0, "unreadable": 1, "complete": True},
    {"scanned": 1, "not_primary": 1, "unreadable": 0, "complete": True},
    {"scanned": True, "not_primary": 0, "unreadable": 0, "complete": True},
    {"scanned": 1, "not_primary": 0, "unreadable": 0, "complete": "yes"},
])
def test_rejects_inconsistent_results(bad):
    with pytest.raises(ValueError):
        summarize_rotation_audit({'a': bad}, expected_scope_ids={'a'})

def test_rejects_duplicate_or_unexpected_scope_count():
    with pytest.raises(ValueError):
        summarize_rotation_audit({'a': result(), 'b': result()}, expected_scope_ids={'a'})

def test_duplicate_scope_cannot_count_twice():
    # Dict input guarantees a scope ID has at most one report.
    assert not summarize_rotation_audit({'a': result()}, expected_scope_ids={'a', 'b'})["complete"]

def test_empty_inventory_is_not_proof_of_completion():
    with pytest.raises(ValueError, match="inventory"):
        summarize_rotation_audit({}, expected_scope_ids=set())

@pytest.mark.parametrize("bad", [None, [], {"a": None}, {"a": 1}])
def test_malformed_audit_inputs_fail_closed(bad):
    with pytest.raises(ValueError):
        summarize_rotation_audit(bad, expected_scope_ids={"a"})

def test_missing_credentials_in_expected_scope_is_not_success():
    with pytest.raises(ValueError, match="no rows"):
        summarize_rotation_audit({'a': result(scanned=0)}, expected_scope_ids={'a'})

def test_stale_inventory_fails_even_when_other_scopes_pass():
    with pytest.raises(ValueError, match="no rows"):
        summarize_rotation_audit({'a': result(), 'b': result(scanned=0)}, expected_scope_ids={'a', 'b'})
