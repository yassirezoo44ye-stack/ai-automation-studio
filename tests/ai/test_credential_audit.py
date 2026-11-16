import pytest
from app.ai.credential_audit import summarize_rotation_audit

def result(scanned=1, not_primary=0, unreadable=0, complete=True):
    return dict(scanned=scanned, not_primary=not_primary, unreadable=unreadable, complete=complete)

def test_all_expected_scopes_verified():
    assert summarize_rotation_audit([result(), result()], expected_scopes=2) == {
        "expected_scopes": 2, "checked_scopes": 2, "scanned": 2,
        "not_primary": 0, "unreadable": 0, "complete": True
    }

def test_missing_scope_blocks_completion():
    assert not summarize_rotation_audit([result()], expected_scopes=2)["complete"]

def test_unreadable_and_old_keys_block_completion():
    assert not summarize_rotation_audit([result(not_primary=1, unreadable=1, complete=False)], expected_scopes=1)["complete"]

@pytest.mark.parametrize("bad", [
    {"scanned": 1, "not_primary": 2, "unreadable": 0, "complete": False},
    {"scanned": 1, "not_primary": 0, "unreadable": 1, "complete": True},
    {"scanned": 1, "not_primary": 1, "unreadable": 0, "complete": True},
    {"scanned": True, "not_primary": 0, "unreadable": 0, "complete": True},
    {"scanned": 1, "not_primary": 0, "unreadable": 0, "complete": "yes"},
])
def test_rejects_inconsistent_results(bad):
    with pytest.raises(ValueError):
        summarize_rotation_audit([bad], expected_scopes=1)

def test_rejects_duplicate_or_unexpected_scope_count():
    with pytest.raises(ValueError):
        summarize_rotation_audit([result(), result()], expected_scopes=1)
