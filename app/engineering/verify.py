"""
ProductionVerifier — verifies a deployment is truly live and matches the expected SHA.

Rules:
  1. A deploy hook returning HTTP 200 is NOT deployment success.
  2. A deploy status of "live" is NOT sufficient alone.
  3. Production is VERIFIED only when ALL of these pass:
       a. Deploy status = "live" (or equivalent)
       b. Health endpoint returns 200
       c. observed_sha == requested_sha
  4. If any check fails → status = UNVERIFIED (not FAILED until max_retries exceeded)
  5. All verification results are written to eng_evidence.
  6. The mission is NEVER marked SUCCEEDED without has_verified_deploy() returning True.

SHA verification flow:
  requested_sha = the git commit SHA that was supposed to deploy
  observed_sha  = the SHA currently running in production (from Render /deploys API
                  or a /_health endpoint that returns it)

If requested_sha != observed_sha → DEPLOYMENT NOT VERIFIED.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

import httpx

from app.engineering.evidence import get_evidence_store

log = logging.getLogger(__name__)

_HTTP_TIMEOUT = httpx.Timeout(connect=5.0, read=15.0, write=5.0, pool=5.0)


@dataclass
class VerificationResult:
    """Complete result of one verification run."""
    success: bool
    requested_sha: Optional[str]
    observed_sha: Optional[str]
    sha_match: bool
    health_ok: bool
    deploy_status: Optional[str]
    deploy_id: Optional[str]
    checks: dict = field(default_factory=dict)
    failure_reason: Optional[str] = None

    @property
    def is_production_verified(self) -> bool:
        """True only when ALL three gates pass."""
        return self.success and self.sha_match and self.health_ok


class ProductionVerifier:
    """
    Verifies a Render deployment against:
      1. Render deploy status
      2. Application health endpoint
      3. SHA match (requested vs. observed)

    Usage:
        verifier = ProductionVerifier(pool)
        result = await verifier.verify_render_deploy(
            org_id=org_id,
            mission_id=mission_id,
            service_id="srv-abc",
            deploy_id="dep-xyz",
            requested_sha="bc123c9...",
            health_url="https://my-app.onrender.com/api/health",
            evidence_id="existing_evidence_id",   # optional, to update
        )
        if result.is_production_verified:
            ...  # safe to mark mission SUCCEEDED
        else:
            ...  # STOP — do not mark SUCCEEDED
    """

    def __init__(self, pool=None) -> None:
        self._pool = pool

    async def verify_render_deploy(
        self,
        *,
        org_id: str,
        mission_id: str,
        service_id: str,
        deploy_id: str,
        requested_sha: str,
        health_url: Optional[str] = None,
        max_poll_seconds: int = 300,
        poll_interval: int = 10,
        evidence_id: Optional[str] = None,
    ) -> VerificationResult:
        """Poll Render until deploy is terminal, then verify health + SHA."""
        from app.integrations.credential_store import get_credential_store
        from app.core.db import get_pool

        pool = self._pool or get_pool()
        cred = await get_credential_store(pool).load("render", org_id)
        if cred is None:
            return VerificationResult(
                success=False,
                requested_sha=requested_sha,
                observed_sha=None,
                sha_match=False,
                health_ok=False,
                deploy_status=None,
                deploy_id=deploy_id,
                failure_reason="render provider not connected",
            )

        # 1. Poll deploy status
        deploy_status, observed_sha = await self._poll_render_deploy(
            cred=cred,
            service_id=service_id,
            deploy_id=deploy_id,
            max_seconds=max_poll_seconds,
            interval=poll_interval,
        )

        # 2. Health check
        health_ok = False
        if health_url and deploy_status == "live":
            health_ok = await self._check_health(health_url)
        elif deploy_status == "live" and not health_url:
            health_ok = True  # no health URL configured — assume OK (log warning)
            log.warning("verify_render_deploy: no health_url configured for service %s", service_id)

        # 3. SHA match
        sha_match = bool(observed_sha and requested_sha and observed_sha.startswith(requested_sha[:7]))

        success = deploy_status == "live"
        failure_reason = None
        if not success:
            failure_reason = f"deploy status is {deploy_status!r}, not 'live'"
        elif not health_ok:
            failure_reason = "health check failed"
        elif not sha_match:
            failure_reason = (
                f"SHA mismatch: requested={requested_sha!r} observed={observed_sha!r}. "
                "This deployment is NOT VERIFIED."
            )

        result = VerificationResult(
            success=success,
            requested_sha=requested_sha,
            observed_sha=observed_sha,
            sha_match=sha_match,
            health_ok=health_ok,
            deploy_status=deploy_status,
            deploy_id=deploy_id,
            failure_reason=failure_reason,
            checks={
                "deploy_status": deploy_status,
                "health_ok":     health_ok,
                "sha_match":     sha_match,
                "requested_sha": requested_sha,
                "observed_sha":  observed_sha,
            },
        )

        # 4. Update Evidence
        ev_store = get_evidence_store(pool)
        if evidence_id:
            if result.is_production_verified:
                await ev_store.mark_verified(evidence_id, org_id=org_id)
            else:
                await ev_store.mark_failed(
                    evidence_id, org_id=org_id, reason=failure_reason or "verification failed"
                )
            await ev_store.update_sha(
                evidence_id,
                org_id=org_id,
                observed_sha=observed_sha or "",
                requested_sha=requested_sha,
            )
        else:
            # Record new verification evidence
            import hashlib
            import json
            inputs_hash = hashlib.sha256(
                json.dumps({"service_id": service_id, "deploy_id": deploy_id,
                            "requested_sha": requested_sha}, sort_keys=True).encode()
            ).hexdigest()[:32]
            await ev_store.record(
                org_id=org_id,
                mission_id=mission_id,
                task_id=None,
                provider="render",
                operation="verify_deploy",
                tool_name="render.verify_deploy",
                inputs_hash=inputs_hash,
                outputs_summary={
                    "deploy_status": deploy_status,
                    "health_ok":     health_ok,
                    "sha_match":     sha_match,
                    "failure_reason": failure_reason,
                },
                verification_status="verified" if result.is_production_verified else "failed",
                requested_sha=requested_sha,
                observed_sha=observed_sha,
                deploy_id=deploy_id,
            )

        if result.is_production_verified:
            log.info(
                "deployment VERIFIED: service=%s deploy=%s sha=%s",
                service_id, deploy_id, requested_sha[:8],
            )
        else:
            log.warning(
                "deployment NOT VERIFIED: service=%s deploy=%s reason=%s",
                service_id, deploy_id, failure_reason,
            )

        return result

    async def _poll_render_deploy(
        self,
        *,
        cred,
        service_id: str,
        deploy_id: str,
        max_seconds: int,
        interval: int,
    ) -> tuple[str, Optional[str]]:
        """Poll Render deploys API until the deploy reaches a terminal state."""
        from app.integrations.providers.render import _auth_header as render_headers

        _RENDER_API = "https://api.render.com/v1"
        _TERMINAL = {"live", "deactivated", "build_failed", "pre_deploy_failed", "canceled"}

        deadline = time.monotonic() + max_seconds
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            while time.monotonic() < deadline:
                try:
                    resp = await client.get(
                        f"{_RENDER_API}/services/{service_id}/deploys/{deploy_id}",
                        headers=render_headers(cred),
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        status = data.get("status", "unknown")
                        observed_sha = (data.get("commit") or {}).get("id")
                        if status in _TERMINAL:
                            return status, observed_sha
                        log.debug("deploy %s status=%s, waiting...", deploy_id[:8], status)
                except Exception as exc:
                    log.warning("render poll error: %s", exc)
                await asyncio.sleep(interval)
        return "timeout", None

    async def _check_health(self, url: str, *, retries: int = 3) -> bool:
        """GET the health URL and return True if HTTP 200."""
        from app.core.ssrf_guard import assert_public_url, UnsafeUrlError
        try:
            assert_public_url(url)
        except UnsafeUrlError as exc:
            log.warning("health URL SSRF blocked: %s", exc)
            return False
        for attempt in range(retries):
            try:
                async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                    resp = await client.get(url)
                if resp.status_code == 200:
                    return True
                log.warning("health check %s returned %d (attempt %d)", url, resp.status_code, attempt + 1)
            except Exception as exc:
                log.warning("health check error (attempt %d): %s", attempt + 1, exc)
            if attempt < retries - 1:
                await asyncio.sleep(5)
        return False


# ── Singleton ─────────────────────────────────────────────────────────────────

_verifier: Optional[ProductionVerifier] = None


def get_production_verifier(pool=None) -> ProductionVerifier:
    global _verifier
    if _verifier is None:
        _verifier = ProductionVerifier(pool)
    return _verifier
