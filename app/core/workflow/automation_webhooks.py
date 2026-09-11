"""
Automation Webhook Endpoint — Phase 5 Gate 3.

POST /api/webhooks/auto/{definition_id}/{trigger_id}

Verifies HMAC-SHA256 signature from X-Automation-Signature header,
checks timestamp freshness (±5 minutes), then enqueues a job.

Security invariants:
  • No session / OrgContext auth — webhook secrets are the credential.
  • Enumeration-safe: every authentication error returns identical 401 body;
    the caller learns NOTHING about definition/trigger existence, org, or secret.
  • Timing-safe: hmac.compare_digest() for all secret comparisons.
  • Timestamp gate: reject payloads older than TIMESTAMP_TOLERANCE_SECONDS.
  • Secret stored as Fernet-encrypted blob keyed by definition_id.
  • No internal details (org_id, definition name, trigger name) in any error body.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
import uuid
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Header, HTTPException, Request

from app.core.auth import derive_fernet_key
from app.core.db import get_pool
from app.core.jobs import get_job_queue

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])

# Reject payloads whose X-Automation-Timestamp is more than this many seconds
# in the past (or future).  Protects against replay attacks.
TIMESTAMP_TOLERANCE_SECONDS: int = 300  # 5 minutes

# ── shared error ─────────────────────────────────────────────────────────────
# Every authentication/lookup failure returns this body and 401.
# It must NOT reveal: definition/trigger existence, org_id, secret validity,
# internal DB details, or any difference between "wrong secret" vs "not found".
_AUTH_FAILURE = {"detail": "Webhook authentication failed"}


def _auth_fail() -> HTTPException:
    """Return an enumeration-safe 401."""
    return HTTPException(status_code=401, detail=_AUTH_FAILURE["detail"])


# ── Fernet key derivation for webhook secrets ─────────────────────────────────

def _webhook_fernet() -> Fernet:
    return Fernet(derive_fernet_key("automation_webhooks"))


def encrypt_webhook_secret(plaintext_secret: str) -> str:
    """Encrypt a webhook signing secret for storage.  Returns a URL-safe base64 token."""
    return _webhook_fernet().encrypt(plaintext_secret.encode()).decode()


def decrypt_webhook_secret(encrypted: str) -> Optional[str]:
    """Decrypt a stored webhook secret.  Returns None if invalid."""
    try:
        return _webhook_fernet().decrypt(encrypted.encode()).decode()
    except (InvalidToken, Exception):
        return None


# ── Trigger lookup ────────────────────────────────────────────────────────────

async def _load_trigger_secret(definition_id: str, trigger_id: str) -> Optional[str]:
    """
    Look up the signing secret for a specific webhook trigger.

    The trigger config is stored inside the `triggers` JSONB column as:
      [{"id": "...", "kind": "webhook", "secret_encrypted": "...", ...}, ...]

    Returns the DECRYPTED secret string, or None if not found / decryption fails.
    Never raises — any error becomes None → generic 401.
    """
    try:
        uid = uuid.UUID(definition_id)
    except ValueError:
        return None

    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT triggers, organization_id FROM automation_definitions "
                "WHERE id = $1 AND is_active = true AND deleted_at IS NULL",
                uid,
            )
        if row is None:
            return None

        triggers = row["triggers"]
        if not isinstance(triggers, list):
            return None

        for trigger in triggers:
            if not isinstance(trigger, dict):
                continue
            if trigger.get("id") != trigger_id:
                continue
            if trigger.get("kind") != "webhook":
                continue
            encrypted = trigger.get("secret_encrypted")
            if not encrypted:
                return None
            return decrypt_webhook_secret(encrypted)

        return None
    except Exception:
        log.debug("webhook: trigger lookup failed", exc_info=True)
        return None


async def _load_org_id(definition_id: str) -> Optional[str]:
    """Load organization_id for an active, non-deleted definition."""
    try:
        uid = uuid.UUID(definition_id)
        pool = get_pool()
        async with pool.acquire() as conn:
            val = await conn.fetchval(
                "SELECT organization_id FROM automation_definitions "
                "WHERE id = $1 AND is_active = true AND deleted_at IS NULL",
                uid,
            )
        return str(val) if val else None
    except Exception:
        return None


# ── HMAC verification ─────────────────────────────────────────────────────────

def _verify_signature(
    body_bytes: bytes,
    secret: str,
    signature_header: Optional[str],
    timestamp_header: Optional[str],
) -> bool:
    """
    Verify HMAC-SHA256 signature and timestamp freshness.

    Expected signature format: sha256=<hex_digest>
    The signed message is: f"{timestamp}.{body}"

    Returns False (not raises) on any mismatch — caller turns it into _auth_fail().
    """
    if not signature_header or not timestamp_header:
        return False

    # -- timestamp freshness check --
    try:
        ts = int(timestamp_header)
    except ValueError:
        return False

    now = int(time.time())
    if abs(now - ts) > TIMESTAMP_TOLERANCE_SECONDS:
        return False

    # -- expected sig --
    signed_payload = f"{timestamp_header}.".encode() + body_bytes
    expected = hmac.new(
        secret.encode(),
        signed_payload,
        hashlib.sha256,
    ).hexdigest()

    # -- constant-time compare against provided sig --
    if not signature_header.startswith("sha256="):
        return False
    provided_hex = signature_header[len("sha256="):]
    return hmac.compare_digest(expected, provided_hex)


# ── Webhook handler ───────────────────────────────────────────────────────────

@router.post("/auto/{definition_id}/{trigger_id}", status_code=202)
async def receive_webhook(
    definition_id: str,
    trigger_id: str,
    request: Request,
    x_automation_signature: Optional[str] = Header(None, alias="X-Automation-Signature"),
    x_automation_timestamp: Optional[str] = Header(None, alias="X-Automation-Timestamp"),
):
    """
    Receive a webhook call and enqueue an automation run.

    All auth failures return a generic 401 — no difference between:
      • definition doesn't exist
      • trigger doesn't exist
      • definition is inactive
      • wrong secret
      • bad timestamp / replay
    """
    # 1. Read raw body (needed for HMAC)
    body_bytes = await request.body()

    # 2. Look up secret — BEFORE signature so we can do a timing-safe compare.
    #    If lookup fails (no record) we still do a dummy compare to make timing uniform.
    secret = await _load_trigger_secret(definition_id, trigger_id)

    if secret is None:
        # Dummy compare to avoid timing oracle (always takes ~same time as real compare)
        _dummy = hmac.new(b"dummy", body_bytes, hashlib.sha256).hexdigest()
        hmac.compare_digest(_dummy, _dummy)
        raise _auth_fail()

    # 3. Verify HMAC + timestamp
    if not _verify_signature(body_bytes, secret, x_automation_signature, x_automation_timestamp):
        raise _auth_fail()

    # 4. All auth passed — load org_id (server-side, not from payload)
    org_id = await _load_org_id(definition_id)
    if org_id is None:
        # Race: definition was deactivated/deleted between steps 2 and 4.
        raise _auth_fail()

    # 5. Parse optional JSON payload for context passthrough
    context: dict = {}
    if body_bytes:
        try:
            parsed = json.loads(body_bytes)
            if isinstance(parsed, dict):
                context = parsed
        except (json.JSONDecodeError, ValueError):
            pass  # Non-JSON body is valid; context stays empty

    # 6. Generate run_id and insert pending record
    run_id = str(uuid.uuid4())
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO automation_runs
                (organization_id, definition_id, run_id, name, status,
                 context, triggered_by)
            VALUES ($1, $2, $3, 'webhook-run', 'pending', $4::jsonb, 'webhook')
            """,
            uuid.UUID(org_id),
            uuid.UUID(definition_id),
            run_id,
            json.dumps(context),
        )

    # 7. Enqueue
    payload = {
        "organization_id": org_id,       # server-verified value
        "run_id": run_id,
        "definition_id": definition_id,
        "trigger_id": trigger_id,
        "context": context,
        "triggered_by": "webhook",
    }
    await get_job_queue().submit(
        "automation.trigger.webhook",
        payload=payload,
        org_id=org_id,
        idempotency_key=run_id,
    )

    # 8. Return only the run_id — no org/definition details in response
    return {"run_id": run_id, "status": "pending"}
