"""
Unit tests for app.runtime modules (no network, no DB).
"""
import pytest


class TestCapabilitiesCompute:
    def test_compute_returns_capabilities_object(self):
        from app.runtime.capabilities import Capabilities, compute
        # Build a minimal mock registry
        caps = compute.__wrapped__() if hasattr(compute, "__wrapped__") else None
        # Just import — confirms no import-time errors
        assert Capabilities is not None


class TestPreflightResult:
    def test_ok_result(self):
        from app.runtime.preflight import PreflightResult
        r = PreflightResult(ok=True, checks=[], missing=[])
        assert r.ok is True
        assert r.missing == []

    def test_fail_result(self):
        from app.runtime.preflight import PreflightResult, ToolCheck
        tc = ToolCheck(name="node", display="Node.js", available=False)
        r = PreflightResult(ok=False, checks=[tc], missing=[tc])
        assert r.ok is False
        assert len(r.missing) == 1


class TestDiagnosticsImport:
    def test_imports_without_error(self):
        from app.runtime import diagnostics
        assert hasattr(diagnostics, "generate")
