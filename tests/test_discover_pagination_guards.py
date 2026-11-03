"""Regression checks for Discover pagination validation.

Structural tests intentionally avoid importing the application or requiring DB secrets.
"""
import ast
from pathlib import Path

import pytest


ROUTER = Path(__file__).resolve().parents[1] / "app" / "routers" / "discover.py"


@pytest.mark.parametrize("function_name", ["public_discover_feed", "my_creations"])
def test_pagination_guard_precedes_database_access(function_name):
    source = ROUTER.read_text(encoding="utf-8")
    module = ast.parse(source)
    function = next(
        node for node in module.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == function_name
    )
    checks = [
        node for node in ast.walk(function)
        if isinstance(node, ast.Compare)
        and any(isinstance(part, ast.Name) and part.id in {"limit", "offset"}
                for part in ast.walk(node))
    ]
    assert len(checks) >= 2, "Both limit and offset must be validated"
    pool_calls = [
        node.lineno for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name) and node.func.id == "get_pool"
    ]
    assert pool_calls, "Expected a database pool call"
    assert all(check.lineno < min(pool_calls) for check in checks)
    assert any(
        isinstance(node, ast.Constant) and node.value == 422
        for node in ast.walk(function)
    ), "Invalid pagination must produce HTTP 422"
