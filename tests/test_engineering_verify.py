"""
Tests: ProductionVerifier — the critical SHA-verification gate.

Rules tested:
  1. HTTP 201/200 from trigger alone is NOT production verified.
  2. sha_match=False → is_production_verified=False.
  3. health_ok=False → is_production_verified=False.
  4. deploy_status != "live" → is_production_verified=False.
  5. All three must pass for is_production_verified=True.
  6. SSRF guard blocks private-IP health URLs.
"""
import pytest
from dataclasses import dataclass
from typing import Optional


# ── VerificationResult ────────────────────────────────────────────────────────

def test_verification_result_all_pass():
    from app.engineering.verify import VerificationResult
    r = VerificationResult(
        success=True,
        requested_sha="abc123",
        observed_sha="abc123",
        sha_match=True,
        health_ok=True,
        deploy_status="live",
        deploy_id="dep-001",
    )
    assert r.is_production_verified is True


def test_verification_result_sha_mismatch():
    from app.engineering.verify import VerificationResult
    r = VerificationResult(
        success=True,
        requested_sha="abc123",
        observed_sha="xyz999",
        sha_match=False,
        health_ok=True,
        deploy_status="live",
        deploy_id="dep-001",
    )
    assert r.is_production_verified is False


def test_verification_result_health_fail():
    from app.engineering.verify import VerificationResult
    r = VerificationResult(
        success=True,
        requested_sha="abc123",
        observed_sha="abc123",
        sha_match=True,
        health_ok=False,       # health check failed
        deploy_status="live",
        deploy_id="dep-001",
    )
    assert r.is_production_verified is False


def test_verification_result_deploy_not_live():
    from app.engineering.verify import VerificationResult
    r = VerificationResult(
        success=False,
        requested_sha="abc123",
        observed_sha="abc123",
        sha_match=True,
        health_ok=True,
        deploy_status="build_failed",
        deploy_id="dep-001",
        failure_reason="deploy status is 'build_failed', not 'live'",
    )
    assert r.is_production_verified is False


def test_verification_result_deploy_none_sha():
    from app.engineering.verify import VerificationResult
    # observed_sha=None should always yield sha_match=False
    r = VerificationResult(
        success=True,
        requested_sha="abc123",
        observed_sha=None,
        sha_match=False,       # computed as None → no match
        health_ok=True,
        deploy_status="live",
        deploy_id="dep-001",
    )
    assert r.is_production_verified is False


# ── _check_health — SSRF guard ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_check_health_blocks_private_ip():
    """
    Health URLs pointing at private IP ranges must be blocked (SSRF).
    assert_public_url is imported locally inside _check_health, so we
    patch it in app.core.ssrf_guard (the actual module that defines it).
    """
    from unittest.mock import patch, AsyncMock
    from app.engineering.verify import ProductionVerifier

    verifier = ProductionVerifier(pool=None)

    class _FakeUnsafe(Exception):
        pass

    # Patch at the source module AND the verify module's local import path
    with patch("app.core.ssrf_guard.assert_public_url",
               side_effect=_FakeUnsafe("SSRF blocked")):
        with patch("app.core.ssrf_guard.UnsafeUrlError", _FakeUnsafe):
            result = await verifier._check_health("http://192.168.1.1/health")

    assert result is False


@pytest.mark.asyncio
async def test_check_health_returns_false_on_non_200():
    from unittest.mock import patch, AsyncMock, MagicMock
    from app.engineering.verify import ProductionVerifier

    verifier = ProductionVerifier(pool=None)

    # SSRF guard passes — patch at source
    with patch("app.core.ssrf_guard.assert_public_url", return_value=None):
        mock_resp = MagicMock()
        mock_resp.status_code = 503

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch("app.engineering.verify.httpx.AsyncClient", return_value=mock_client):
            result = await verifier._check_health("https://example.onrender.com/health", retries=1)

    assert result is False


@pytest.mark.asyncio
async def test_check_health_returns_true_on_200():
    from unittest.mock import patch, AsyncMock, MagicMock
    from app.engineering.verify import ProductionVerifier

    verifier = ProductionVerifier(pool=None)

    with patch("app.core.ssrf_guard.assert_public_url", return_value=None):
        mock_resp = MagicMock()
        mock_resp.status_code = 200

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch("app.engineering.verify.httpx.AsyncClient", return_value=mock_client):
            result = await verifier._check_health("https://example.onrender.com/health")

    assert result is True


# ── SHA match logic ───────────────────────────────────────────────────────────

def test_sha_match_prefix_logic():
    """The verifier uses startswith(requested[:7]) to allow short SHA references."""
    from app.engineering.verify import VerificationResult

    # Partial SHA match (Render returns full 40-char SHA, we might request 7)
    requested = "abc1234"
    observed  = "abc1234f9e8d7c6b5a4..."[:40]

    sha_match = observed.startswith(requested[:7])
    r = VerificationResult(
        success=True,
        requested_sha=requested,
        observed_sha=observed,
        sha_match=sha_match,
        health_ok=True,
        deploy_status="live",
        deploy_id="dep-x",
    )
    assert r.sha_match is True
    assert r.is_production_verified is True


def test_sha_match_fails_on_different_sha():
    from app.engineering.verify import VerificationResult
    requested = "abc1234"
    observed  = "xyz9999"
    sha_match = observed.startswith(requested[:7])
    r = VerificationResult(
        success=True,
        requested_sha=requested,
        observed_sha=observed,
        sha_match=sha_match,
        health_ok=True,
        deploy_status="live",
        deploy_id="dep-x",
    )
    assert r.sha_match is False
    assert r.is_production_verified is False
