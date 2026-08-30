"""
Unit tests for the WS ticket system (app/routers/ws_ticket.py).

Verifies:
  • issue_ticket() creates a non-empty opaque token
  • consume_ticket() returns the correct user_id on first use
  • consume_ticket() returns None on second use (single-use)
  • consume_ticket() returns None for unknown tickets
  • Expired tickets are rejected
  • _MAX_TICKETS cap triggers RuntimeError
"""
from __future__ import annotations

import time
from unittest.mock import patch

import pytest

# Prevent DB / config load from failing in unit test context
import os
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
os.environ.setdefault("SESSION_SECRET", "test-secret-for-unit-tests-do-not-use-in-prod")

from app.routers.ws_ticket import issue_ticket, consume_ticket, _store, _lock, _TTL_S


def _drain_store():
    """Clear the ticket store between tests."""
    with _lock:
        _store.clear()


class TestIssueTicket:
    def setup_method(self):
        _drain_store()

    def test_returns_non_empty_string(self):
        ticket = issue_ticket("user-abc")
        assert isinstance(ticket, str)
        assert len(ticket) == 64  # 32-byte hex

    def test_stored_in_store(self):
        ticket = issue_ticket("user-abc")
        assert ticket in _store

    def test_stored_with_correct_user_id(self):
        ticket = issue_ticket("user-xyz")
        assert _store[ticket]["user_id"] == "user-xyz"

    def test_two_tickets_are_unique(self):
        t1 = issue_ticket("u1")
        t2 = issue_ticket("u2")
        assert t1 != t2

    def test_raises_when_store_full(self):
        from app.routers.ws_ticket import _MAX_TICKETS
        with patch("app.routers.ws_ticket._MAX_TICKETS", 1):
            issue_ticket("u1")
            with pytest.raises(RuntimeError, match="full"):
                issue_ticket("u2")


class TestConsumeTicket:
    def setup_method(self):
        _drain_store()

    def test_valid_ticket_returns_user_id(self):
        ticket = issue_ticket("alice")
        result = consume_ticket(ticket)
        assert result == "alice"

    def test_single_use_second_call_returns_none(self):
        ticket = issue_ticket("alice")
        consume_ticket(ticket)
        assert consume_ticket(ticket) is None

    def test_unknown_ticket_returns_none(self):
        assert consume_ticket("not-a-real-ticket") is None

    def test_empty_ticket_returns_none(self):
        assert consume_ticket("") is None

    def test_expired_ticket_returns_none(self):
        ticket = issue_ticket("bob")
        # Manually backdate the expiry
        with _lock:
            _store[ticket]["exp"] = time.monotonic() - 1.0
        assert consume_ticket(ticket) is None

    def test_ticket_removed_after_consume(self):
        ticket = issue_ticket("charlie")
        consume_ticket(ticket)
        assert ticket not in _store

    def test_expired_ticket_removed_from_store(self):
        ticket = issue_ticket("dave")
        with _lock:
            _store[ticket]["exp"] = time.monotonic() - 1.0
        consume_ticket(ticket)
        assert ticket not in _store


class TestPurge:
    def setup_method(self):
        _drain_store()

    def test_issue_purges_expired(self):
        """Calling issue_ticket() must evict already-expired tickets."""
        t1 = issue_ticket("user1")
        with _lock:
            _store[t1]["exp"] = time.monotonic() - 1.0
        # Issue a new ticket → triggers _purge
        issue_ticket("user2")
        assert t1 not in _store
