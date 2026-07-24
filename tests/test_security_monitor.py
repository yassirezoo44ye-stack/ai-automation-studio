"""
Regression tests for two false-positives found during the v1.0 Phase 8
production-readiness E2E run — booting the real app locally logged 4
CRITICAL "possible secret found" alerts from app.services.security_monitor:

1. tests/test_architecture.py, tests/test_observability.py, tests/
   security/test_provider_security.py — all intentional fake secret-shaped
   strings used to exercise the secret-detection/log-masking code itself.
   scripts/ci_secret_scan.py already excludes tests/ for the identical
   reason; security_monitor.py's own runtime scan never got that exclusion.

2. app/integrations/oauth.py's OAuthProviderConfig.__repr__ — matched the
   secret= pattern via `client_secret='***REDACTED***'`, i.e. the code
   whose entire job is keeping a real secret OUT of logs/reprs was itself
   flagged as leaking one. This file ships in the Docker image, so unlike
   (1) this false positive fires on every real production boot, not just
   local/dev.
"""
import os

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
os.environ.setdefault("SESSION_SECRET", "test-secret-for-unit-tests-do-not-use-in-prod")

from app.services.security_monitor import _scan  # noqa: E402


class TestSecurityMonitorScan:
    def test_scan_does_not_flag_known_test_fixtures(self):
        """These 3 files are confirmed (by direct inspection) to contain
        only fake, test-only secret-shaped strings — none should appear
        in _scan()'s hits."""
        hits = _scan()
        known_fixtures = {
            "tests\\test_architecture.py", "tests/test_architecture.py",
            "tests\\test_observability.py", "tests/test_observability.py",
            "tests\\security\\test_provider_security.py",
            "tests/security/test_provider_security.py",
        }
        flagged_fixtures = set(hits) & known_fixtures
        assert not flagged_fixtures, (
            f"security_monitor flagged known test fixtures as leaked "
            f"secrets: {flagged_fixtures}"
        )

    def test_scan_still_flags_a_real_looking_secret_outside_tests(self, tmp_path, monkeypatch):
        """The exclusion must be scoped to tests/, not disable detection
        entirely — a secret-shaped string in a non-test file must still
        be caught."""
        import app.services.security_monitor as sm

        monkeypatch.setattr(sm, "_ROOT", tmp_path)
        (tmp_path / "config_leak.py").write_text(
            'password = "definitely_not_a_placeholder"\n', encoding="utf-8"
        )
        hits = sm._scan()
        assert "config_leak.py" in hits

    def test_scan_does_not_flag_oauth_repr_redaction(self):
        """app/integrations/oauth.py ships in the Docker image (unlike
        tests/) — this false positive fires on every real production boot
        until fixed, not just local dev."""
        hits = _scan()
        assert "app\\integrations\\oauth.py" not in hits
        assert "app/integrations/oauth.py" not in hits

    def test_scan_does_not_flag_a_redacted_value(self, tmp_path, monkeypatch):
        """Narrower unit check of the same fix: a literal ***REDACTED***
        placeholder must never itself read as a leaked secret."""
        import app.services.security_monitor as sm

        monkeypatch.setattr(sm, "_ROOT", tmp_path)
        (tmp_path / "safe_repr.py").write_text(
            "def __repr__(self):\n"
            "    return f\"Config(client_secret='***REDACTED***')\"\n",
            encoding="utf-8",
        )
        hits = sm._scan()
        assert "safe_repr.py" not in hits
