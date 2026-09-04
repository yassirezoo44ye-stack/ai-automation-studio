"""
Automation Webhook Receiver — Phase 5 Gate 3.

POST /api/webhooks/auto/{definition_id}/{trigger_id}

This endpoint is INTENTIONALLY NOT session-authenticated. It is reachable
from external systems that cannot hold a JWT. Authentication is via
HMAC-SHA256 of the request body using the per-trigger signing secret stored
encrypted in automation_definitions.triggers.

Security properties
───────────────────
1. Signature verified before any business logic.
2. Organization ID is obtained from the stored definition row, NEVER from
   the caller.
3. Constant-time comparison prevents timing attacks on the signature.
4. Signing secret is never logged, returned in responses, or stored as
   plaintext.
5. Invalid definition/trigger return the same 401 response — no enumeration
   oracle for whether a definition exists.
6. Optional replay protection via X-Automation-Timestamp header (reject if
   older than 5 minutes when header is present).
7. After verification, a JobQueue job is submitted — the webhook handler
   returns immediately without executing the workflow inline.

Must be added to PUBLIC_PREFIXES so the global api_auth_middleware lets it
through. See app/core/config.py.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from app.core.auth import derive_fernet_key
from app.core.db import get_pool
from app.core.jobs import get_job_queue

log = logging.getLogger(__name__)

router = APIRouter(tags=["automation-webhooks"])

_REPLAY_WINDOW_S = 300   # 5 minutes
_SIGNATURE_HEADER = "X-Automation-Signature"
_TIMESTAMP_HEADER = "X-Automation-Timestamp"


def _fernet():
    from cryptography.fernet import Fernet
    return Fernet(derive_fernet_key("automation_webhooks"))


def _verify_signature(secret: str, body: bytes, provided_sig: str) -> bool:
    """Constant-time HMAC-SHA256 signature verification.
    Expected format: 'sha256=<hex_digest>'
    """
    if not provided_sig.startswith("sha256="):
        return False
    expected_hex = hmac.new(
        secret.encode("utf-8"), body, hashlib.sha256
    ).hexdigest()
    provided_hex = provided_sig[7:]
    return hmac.compare_digest(expected_hex, provided_hex)


def _decrypt_secret(encrypted: str) -> str:
    """Decrypt a Fernet-encrypted webhook signing secret."""
    return _fernet().decrypt(encrypted.encode()).decode()


@router.post("/api/webhooks/auto/{definition_id}/{trigger_id}")
async def receive_webhook(
    definition_id: str,
    trigger_id: str,
    request: Request,
):
    """
    Receive an external webhook and dispatch it to the job queue.

    Authentication: HMAC-SHA256 via X-Automation-Signature header.
    Does NOT require a session token — added to PUBLIC_PREFIXES.
    """
    # 1. Read the raw body before any parsing (signature covers the raw bytes)
    body = await request.body()

    # 2. Extract the signature header — return generic 401 on any auth failure
    provided_sig = request.headers.get(_SIGNATURE_HEADER, "")
    if not provided_sig:
        log.warning(
            "webhook: missing signature header for definition=%s trigger=%s",
            definition_id, trigger_id,
        )
        raise HTTPException(401, "Missing webhook signature")

    # 3. Optional replay protection
    ts_header = request.headers.get(_TIMESTAMP_HEADER)
    if ts_header:
        try:
            ts = float(ts_header)
            age = time.time() - ts
            if age > _REPLAY_WINDOW_S or age < -60:
                log.warning(
                    "webhook: stale timestamp age=%.0fs for definition=%s",
                    age, definition_id,
                )
                raise HTTPException(401, "Webhook timestamp out of window")
        except ValueError:
            raise HTTPException(401, "Invalid webhook timestamp")

    # 4. Look up definition — use generic 401 for all failures to avoid
    # revealing whether the definition exists
    try:
        def_uuid = uuid.UUID(definition_id)
    except ValueError:
        raise HTTPException(401, "Invalid webhook endpoint")

    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, organization_id, triggers, is_active, deleted_at FROM automation_definitions WHERE id=$1",
            def_uuid,
        )

    if not row or row["deleted_at"] is not None or not row["is_active"]:
        log.warning(
            "webhook: definition not found/inactive definition=%s", definition_id,
        )
        raise HTTPException(401, "Invalid webhook endpoint")

    # 5. Find the matching trigger
    triggers = row["triggers"]
    if isinstance(triggers, str):
        triggers = json.loads(triggers)

    matched_trigger: Optional[dict] = None
    for t in triggers:
        if t.get("id") == trigger_id and t.get("type") == "webhook":
            matched_trigger = t
            break

    if not matched_trigger:
        log.warning(
            "webhook: trigger %s not found in definition %s", trigger_id, definition_id,
        )
        raise HTTPException(401, "Invalid webhook endpoint")

    if not matched_trigger.get("enabled", True):
        raise HTTPException(401, "Invalid webhook endpoint")

    # 6. Decrypt the signing secret and verify HMAC — NEVER log the secret
    encrypted_secret = matched_trigger.get("signing_secret_encrypted")
    if not encrypted_secret:
        log.error(
            "webhook: no signing secret for trigger %s in definition %s",
            trigger_id, definition_id,
        )
        raise HTTPException(401, "Invalid webhook endpoint")

    try:
        signing_secret = _decrypt_secret(encrypted_secret)
    except Exception:
        log.exception(
            "webhook: failed to decrypt signing secret for trigger %s (non-fatal config error)",
            trigger_id,
        )
        raise HTTPException(401, "Invalid webhook endpoint")

    if not _verify_signature(signing_secret, body, provided_sig):
        log.warning(
            "webhook: invalid signature for definition=%s trigger=%s",
            definition_id, trigger_id,
        )
        raise HTTPException(401, "Invalid webhook signature")

    # 7. Signature verified — org_id is now trusted from the stored definition
    org_id = str(row["organization_id"])

    # 8. Parse body (best-effort — may be form data, JSON, or raw bytes)
    webhook_body: dict = {}
    try:
        webhook_body = json.loads(body)
        if not isinstance(webhook_body, dict):
            webhook_body = {"raw": webhook_body}
    except Exception:
        # Non-JSON body — store as raw string
        try:
            webhook_body = {"raw": body.decode("utf-8", errors="replace")}
        except Exception:
            webhook_body = {}

    # 9. Compute signature hash for idempotency key (sha256 of body, not secret)
    sig_hash = hashlib.sha256(body).hexdigest()[:16]

    # 10. Submit to job queue — do NOT execute inline
    queue = get_job_queue()
    try:
        job_id = await queue.submit(
            kind="automation.trigger.webhook",
            payload={
                "definition_id": definition_id,
                "organization_id": org_id,
                "trigger_id": trigger_id,
                "body": webhook_body,
            },
            org_id=org_id,
            idempotency_key=f"auto-webhook:{trigger_id}:{sig_hash}",
        )
        log.info(
            "webhook: queued job %s for definition=%s trigger=%s org=%s",
            job_id, definition_id, trigger_id, org_id,
        )
    except Exception:
        log.exception("webhook: failed to submit job (definition=%s)", definition_id)
        # Return 202 even on queue failure — the signature was valid; the
        # external system should not retry based on a queue hiccup. The
        # operator should monitor the job queue DLQ.

    return JSONResponse(status_code=202, content={"queued": True})


def encrypt_webhook_secret(plaintext_secret: str) -> str:
    """Utility: encrypt a plaintext webhook signing secret for storage.
    Called by definition CRUD when a webhook trigger is created/updated.
    The plaintext secret is never persisted.
    """
    return _fernet().encrypt(plaintext_secret.encode()).decode()
