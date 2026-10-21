"""
Integration tests for AppBuilderService.generate_spec() — AI gateway mocked.

Covers the four paths through generate_spec():
  1. Valid JSON on first attempt                → returns AppSpec
  2. Broken JSON (unescaped quote) first attempt,
     valid JSON on retry                        → returns AppSpec (retry path)
  3. Broken JSON on both attempts               → raises ValueError (retry exhausted)
  4. Truncated JSON on first attempt            → raises ValueError immediately,
                                                  no second gateway call

No live DB, no network, no AI calls.
"""
from __future__ import annotations

import json
import os
import sys
import unittest.mock as mock

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
os.environ.setdefault("SESSION_SECRET", "test-secret-for-unit-tests-do-not-use-in-prod")

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

_MOCKS = {
    "asyncpg": mock.MagicMock(),
    "app.ai": mock.MagicMock(),
    "app.ai.gateway": mock.MagicMock(),
    "app.ai.models": mock.MagicMock(),
    "app.core": mock.MagicMock(),
    "app.core.db": mock.MagicMock(),
}

with mock.patch.dict(sys.modules, _MOCKS):
    from app.services.app_builder import AppBuilderService

# The dict generate_spec looks up globals in (same object used at import time)
_ab_globals = AppBuilderService.generate_spec.__globals__

# ── Minimal valid spec JSON (passes _parse_and_validate_spec) ─────────────────

_VALID_SPEC = json.dumps({
    "name": "inventory_app",
    "description": "Track warehouse stock.",
    "target_users": "warehouse staff",
    "entities": [
        {
            "name": "product",
            "display_name": "Product",
            "columns": [
                {"name": "sku", "type": "text", "nullable": False},
                {"name": "quantity", "type": "integer", "nullable": True},
            ],
            "relationships": [],
        }
    ],
    "pages": [{"name": "Products", "entity": "product", "kind": "list"}],
    "roles": [],
    "workflows": [],
    "agents": [],
    "integrations": [],
    "settings": {},
    "multi_device_config": None,
})

# Production error pattern: unescaped double-quote inside system_prompt value.
# This matches the historical error "Expecting ',' delimiter".
_BROKEN_UNESCAPED_QUOTE = (
    '{"name": "deals_app", "description": "Find deals.", "target_users": "users", '
    '"entities": [], "pages": [], "roles": [], "workflows": [], '
    '"agents": [{"name": "DealFinder", "description": "Finds deals.", '
    '"system_prompt": "Help find "the best" deals."}], '
    '"integrations": [], "settings": {}, "multi_device_config": null}'
)

# Truncated response: last character is not '}' or ']' — detected by _looks_truncated.
_TRUNCATED = '{"name": "app", "entities": [{"name": "pro'


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_service() -> AppBuilderService:
    """Return an AppBuilderService whose AI gateway is a fresh AsyncMock."""
    pool = mock.MagicMock()
    svc = AppBuilderService.__new__(AppBuilderService)
    svc._pool = pool
    svc._gw = mock.AsyncMock()
    return svc


def _gateway_response(content: str) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.content = content
    return resp


# ── Tests ─────────────────────────────────────────────────────────────────────

async def test_generate_spec_valid_first_attempt():
    """Gateway returns valid JSON on first call → AppSpec returned, no retry."""
    svc = _make_service()
    svc._gw.complete = mock.AsyncMock(
        return_value=_gateway_response(_VALID_SPEC)
    )

    spec = await svc.generate_spec(
        "warehouse inventory tracker",
        org_id="org-1",
        user_id="user-1",
    )

    # One gateway call only — no retry
    assert svc._gw.complete.call_count == 1
    # Returned spec carries the name from the JSON
    assert spec.name == "inventory_app"


async def test_generate_spec_broken_json_then_fixed_on_retry():
    """
    First gateway call returns JSON with unescaped double-quote (production error
    pattern: 'Expecting ',' delimiter').  _looks_truncated returns False for this
    (balanced braces), so the retry path runs.  Second call returns valid JSON.
    """
    svc = _make_service()
    svc._gw.complete = mock.AsyncMock(side_effect=[
        _gateway_response(_BROKEN_UNESCAPED_QUOTE),  # first call: broken
        _gateway_response(_VALID_SPEC),               # retry: fixed
    ])

    _cr = mock.MagicMock(side_effect=lambda **kw: type("R", (), kw)())
    _msg = mock.MagicMock(side_effect=lambda **kw: type("M", (), kw)())
    with mock.patch.dict(_ab_globals, {"CompletionRequest": _cr, "Message": _msg}):
        spec = await svc.generate_spec(
            "deals finder app",
            org_id="org-1",
            user_id="user-1",
        )

    # Exactly two gateway calls: first attempt + one retry
    assert svc._gw.complete.call_count == 2
    # Retry used temperature=0.1 (lower than the initial 0.3)
    _, retry_kwargs = svc._gw.complete.call_args_list[1]
    retry_request = svc._gw.complete.call_args_list[1][0][0]
    assert retry_request.temperature == 0.1, (
        "Retry must use temperature=0.1 to reduce model creativity"
    )
    # Spec from the valid retry response
    assert spec.name == "inventory_app"


async def test_generate_spec_both_attempts_fail():
    """Both calls return broken JSON → ValueError raised, message mentions retry."""
    svc = _make_service()
    svc._gw.complete = mock.AsyncMock(side_effect=[
        _gateway_response(_BROKEN_UNESCAPED_QUOTE),
        _gateway_response(_BROKEN_UNESCAPED_QUOTE),
    ])

    with pytest.raises(ValueError, match="Could not generate a valid app spec after retrying"):
        await svc.generate_spec(
            "deals finder app",
            org_id="org-1",
            user_id="user-1",
        )

    # Both calls were made
    assert svc._gw.complete.call_count == 2


async def test_generate_spec_truncated_response_no_retry():
    """
    Truncated response → _looks_truncated returns True → ValueError raised
    immediately with 'cut off' message, without a second gateway call.

    This is the critical path: retrying a truncated response would fail
    (the model would just produce another truncated response), so the function
    correctly aborts early and asks the user to simplify their description.
    """
    svc = _make_service()
    svc._gw.complete = mock.AsyncMock(
        return_value=_gateway_response(_TRUNCATED)
    )

    with pytest.raises(ValueError, match="cut off"):
        await svc.generate_spec(
            "very complex enterprise app with many features",
            org_id="org-1",
            user_id="user-1",
        )

    # Only one gateway call — no retry attempted on truncation
    assert svc._gw.complete.call_count == 1, (
        "generate_spec must NOT retry a truncated response; "
        "retrying would waste a token budget on a response that cannot be fixed"
    )


async def test_generate_spec_include_automation_appends_to_prompt():
    """include_automation=True appends the automation instruction to user content."""
    svc = _make_service()
    svc._gw.complete = mock.AsyncMock(
        return_value=_gateway_response(_VALID_SPEC)
    )

    _cr = mock.MagicMock(side_effect=lambda **kw: type("R", (), kw)())
    _msg = mock.MagicMock(side_effect=lambda **kw: type("M", (), kw)())
    with mock.patch.dict(_ab_globals, {"CompletionRequest": _cr, "Message": _msg}):
        await svc.generate_spec(
            "task manager",
            include_automation=True,
            org_id="org-1",
            user_id="user-1",
        )

    first_request = svc._gw.complete.call_args_list[0][0][0]
    user_message_content = first_request.messages[0].content
    assert "workflows and AI agents" in user_message_content, (
        "include_automation=True must append automation instruction to user message"
    )


async def test_generate_spec_retry_includes_original_response_in_messages():
    """
    On retry, the fix request must include the original (broken) assistant response
    so the model can see what it produced and correct it.
    """
    svc = _make_service()
    svc._gw.complete = mock.AsyncMock(side_effect=[
        _gateway_response(_BROKEN_UNESCAPED_QUOTE),
        _gateway_response(_VALID_SPEC),
    ])

    _cr = mock.MagicMock(side_effect=lambda **kw: type("R", (), kw)())
    _msg = mock.MagicMock(side_effect=lambda **kw: type("M", (), kw)())
    with mock.patch.dict(_ab_globals, {"CompletionRequest": _cr, "Message": _msg}):
        await svc.generate_spec("test app", org_id="org-1", user_id="user-1")

    retry_request = svc._gw.complete.call_args_list[1][0][0]
    message_roles = [m.role for m in retry_request.messages]
    assert "assistant" in message_roles, (
        "Retry request must include the original assistant response so the model "
        "can see and correct its own malformed output"
    )
    # The assistant message must contain the broken response content
    assistant_msgs = [m for m in retry_request.messages if m.role == "assistant"]
    assert assistant_msgs[0].content == _BROKEN_UNESCAPED_QUOTE
