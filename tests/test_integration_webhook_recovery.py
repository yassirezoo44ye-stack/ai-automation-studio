"""
app/integrations/webhooks.py's receive_webhook() recovery fix — regression
tests for the bug this closes: a delivery whose provider.handle_webhook()
raised after the dedup_key row was already committed previously had no way
to recover (no processed_at/error columns), so any redelivery of that exact
event hit the UNIQUE(dedup_key) conflict and was silently swallowed as a
permanent duplicate forever. This mirrors app/billing/webhooks.py's
WebhookEventService.record() retry-vs-duplicate distinction, which already
has this correctly.

Uses a lightweight fake pool/connection (mirrors tests/test_idempotency.py's
FakeIdempotencyPool convention) rather than a live DB — this module only
needs INSERT..ON CONFLICT..RETURNING, one SELECT, and two UPDATEs.
"""
from __future__ import annotations

import sys
import unittest
import unittest.mock
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.integrations.webhooks import (
    WebhookDuplicateError,
    WebhookVerificationError,
    receive_webhook,
)


def _norm(q: str) -> str:
    return " ".join(q.split())


class FakeWebhookConn:
    def __init__(self, rows: dict):
        self.rows = rows  # dedup_key -> {"processed_at": .., "error": ..}

    async def fetchval(self, query, *args):
        q = _norm(query)
        assert q.startswith("INSERT INTO integration_webhook_events")
        _id, _provider_id, _org_id, dedup_key, _ts = args
        if dedup_key in self.rows:
            return None
        self.rows[dedup_key] = {"processed_at": None, "error": None}
        return uuid.uuid4()

    async def fetchrow(self, query, *args):
        q = _norm(query)
        assert q.startswith("SELECT processed_at, error FROM integration_webhook_events")
        (dedup_key,) = args
        row = self.rows.get(dedup_key)
        return row


class FakeWebhookPool:
    def __init__(self, rows: dict | None = None):
        self.rows = rows if rows is not None else {}
        self._conn = FakeWebhookConn(self.rows)

    def acquire(self):
        return _AcquireCM(self._conn)

    async def execute(self, query, *args):
        q = _norm(query)
        assert q.startswith("UPDATE integration_webhook_events")
        dedup_key = args[0]
        row = self.rows.setdefault(dedup_key, {"processed_at": None, "error": None})
        if "processed_at=NOW()" in q:
            row["processed_at"] = "now"
            row["error"] = None
        elif "processed_at=NULL" in q:
            row["processed_at"] = None
            row["error"] = args[1]
        return "UPDATE 1"


class _AcquireCM:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc):
        return False


class _FakeCredential:
    organization_id = str(uuid.uuid4())
    secrets = {"webhook_secret": "shh"}


class _FakeProvider:
    provider_id = "fake-provider"

    def __init__(self, *, verify=True, handle_raises: Exception | None = None):
        self._verify = verify
        self._handle_raises = handle_raises
        self.handled = []

    def verify_webhook_signature(self, event, secret):
        return self._verify

    async def handle_webhook(self, credential, event):
        if self._handle_raises:
            raise self._handle_raises
        self.handled.append(event)


class TestReceiveWebhookRecovery(unittest.IsolatedAsyncioTestCase):
    async def test_verification_failure_raises_before_any_db_write(self):
        pool = FakeWebhookPool()
        provider = _FakeProvider(verify=False)
        with self.assertRaises(WebhookVerificationError):
            await receive_webhook(
                provider=provider, credential=_FakeCredential(),
                headers={}, body=b"{}", pool=pool,
            )
        self.assertEqual(pool.rows, {})

    async def test_first_delivery_processes_and_marks_completed(self):
        pool = FakeWebhookPool()
        provider = _FakeProvider()
        event = await receive_webhook(
            provider=provider, credential=_FakeCredential(),
            headers={}, body=b"{}", pool=pool,
        )
        self.assertEqual(len(provider.handled), 1)
        row = next(iter(pool.rows.values()))
        self.assertEqual(row["processed_at"], "now")
        self.assertIsNone(row["error"])
        self.assertIsNotNone(event)

    async def test_true_duplicate_after_success_raises_without_reprocessing(self):
        pool = FakeWebhookPool()
        provider = _FakeProvider()
        cred = _FakeCredential()
        await receive_webhook(provider=provider, credential=cred, headers={}, body=b"{}", pool=pool)
        self.assertEqual(len(provider.handled), 1)

        with self.assertRaises(WebhookDuplicateError):
            await receive_webhook(provider=provider, credential=cred, headers={}, body=b"{}", pool=pool)
        self.assertEqual(len(provider.handled), 1)  # not reprocessed

    async def test_failed_delivery_is_not_a_permanent_duplicate(self):
        """The actual regression: a delivery that fails must be retried
        successfully on redelivery, not swallowed as a duplicate forever."""
        pool = FakeWebhookPool()
        cred = _FakeCredential()

        failing_provider = _FakeProvider(handle_raises=RuntimeError("downstream boom"))
        with self.assertRaises(RuntimeError):
            await receive_webhook(
                provider=failing_provider, credential=cred, headers={}, body=b"{}", pool=pool,
            )
        row = next(iter(pool.rows.values()))
        self.assertIsNone(row["processed_at"])
        self.assertEqual(row["error"], "downstream boom")

        # Redelivery of the identical event (same headers/body -> same
        # dedup_key) must be treated as a retry, not raise WebhookDuplicateError.
        recovering_provider = _FakeProvider()
        event = await receive_webhook(
            provider=recovering_provider, credential=cred, headers={}, body=b"{}", pool=pool,
        )
        self.assertEqual(len(recovering_provider.handled), 1)
        self.assertIsNotNone(event)
        row = next(iter(pool.rows.values()))
        self.assertEqual(row["processed_at"], "now")
        self.assertIsNone(row["error"])


if __name__ == "__main__":
    unittest.main()
