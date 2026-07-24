"""
Security Regression Suite — Authorization (RBAC / permission gating).

Distinct from test_tool_authorization.py (the AI Tool Dispatcher's
allowed_tools mechanism specifically): this file covers router-level
permission dependencies — which endpoints require which permission, and
that mutating/ownership-sensitive actions can't be driven by raw,
unverified request headers.

Relocated (unmodified) from tests/test_integrations.py and
tests/test_enterprise.py as part of the Security Testing phase's
tests/security/ reorganization. No behavioral change.
"""
from __future__ import annotations

import unittest


# ═══════════════════════════════════════════════════════════════════════════════
# Integrations router — permission gating (from tests/test_integrations.py)
# ═══════════════════════════════════════════════════════════════════════════════

class TestIntegrationsRouterGating:
    """Matches tests/test_enterprise.py's gating-verification convention:
    require_permission() returns a fresh closure per call, so equality is
    checked via __qualname__ + the resource/action baked into the closure's
    repr, not object identity."""

    def _gated_resource_action(self, endpoint):
        import inspect
        from app.tenancy.context import require_permission
        for p in inspect.signature(endpoint).parameters.values():
            if p.default is not inspect.Parameter.empty and hasattr(p.default, "dependency"):
                dep = p.default.dependency
                if getattr(dep, "__qualname__", "") == require_permission("x", "y").__qualname__:
                    return dep
        return None

    def test_providers_and_list_gated_on_read(self):
        from app.routers.integrations import list_providers, list_connections
        assert self._gated_resource_action(list_providers) is not None
        assert self._gated_resource_action(list_connections) is not None

    def test_mutating_endpoints_gated_on_manage(self):
        from app.routers.integrations import connect, disconnect, trigger_sync
        for endpoint in (connect, disconnect, trigger_sync):
            assert self._gated_resource_action(endpoint) is not None

    def test_webhook_endpoint_has_no_permission_dependency(self):
        """External senders can't attach a bearer token — the router must
        not require org auth on this route (signature verification is the
        auth), mirroring /api/stripe/webhook."""
        import inspect
        from app.routers.integrations import receive_webhook
        for p in inspect.signature(receive_webhook).parameters.values():
            if p.default is not inspect.Parameter.empty and hasattr(p.default, "dependency"):
                assert "require_permission" not in repr(p.default.dependency)


# ═══════════════════════════════════════════════════════════════════════════════
# Marketplace router — auth/ownership regression (from tests/test_enterprise.py)
# ═══════════════════════════════════════════════════════════════════════════════

class TestMarketplaceAuthRegression(unittest.TestCase):
    """Regression: publish_listing/update_listing/delete_listing/
    install_listing/submit_review originally had zero auth dependency —
    anyone could publish/update/delete any listing, and install/spoof an
    org via the X-Organization-Id header with zero membership verification.
    Every mutating endpoint must now depend on org_context/require_permission/
    get_current_user, matching test_legacy_api_keys_router_requires_
    authentication's source-inspection pattern from the tenancy phase."""

    def _depends_on(self, fn, target):
        import inspect
        sig = inspect.signature(fn)
        return any(
            getattr(p.default, "dependency", None) is target
            for p in sig.parameters.values()
        )

    def test_publish_update_require_publish_permission(self):
        from app.routers import marketplace
        from app.tenancy.context import require_permission
        import inspect
        for name in ("publish_listing", "update_listing"):
            fn = getattr(marketplace, name)
            sig = inspect.signature(fn)
            # require_permission(...) returns a fresh closure each call, so
            # compare by dependency-factory source rather than identity.
            gated = any(
                getattr(p.default, "dependency", None) is not None
                and getattr(p.default.dependency, "__qualname__", "") == require_permission("marketplace", "publish").__qualname__
                for p in sig.parameters.values()
            )
            self.assertTrue(gated, f"{name} must Depends(require_permission(...))")

    def test_delete_requires_manage_permission(self):
        from app.routers import marketplace
        import inspect
        sig = inspect.signature(marketplace.delete_listing)
        self.assertTrue(
            any(p.default is not None and hasattr(p.default, "dependency") for p in sig.parameters.values()),
            "delete_listing must have a permission dependency",
        )

    def test_install_uninstall_require_org_context(self):
        from app.routers import marketplace
        from app.tenancy import org_context
        for name in ("install_listing", "uninstall_listing"):
            fn = getattr(marketplace, name)
            self.assertTrue(
                self._depends_on(fn, org_context),
                f"{name} must Depends(org_context) — no more spoofable X-Organization-Id header reads",
            )

    def test_install_listing_no_longer_reads_raw_request_headers(self):
        """The original bug: install_listing read request.headers.get(
        'X-Organization-Id')/'X-User-Email' directly with zero verification
        of membership. Guard against that pattern silently coming back."""
        import inspect
        from app.routers import marketplace
        source = inspect.getsource(marketplace.install_listing)
        self.assertNotIn("request.headers", source)
        self.assertNotIn('"X-Organization-Id"', source)

    def test_submit_review_requires_authenticated_user(self):
        from app.routers import marketplace
        from app.routers.auth_users import get_current_user
        self.assertTrue(
            self._depends_on(marketplace.submit_review, get_current_user),
            "submit_review must Depends(get_current_user) — reviewer must come from the token, not client input",
        )

    def test_review_request_has_no_client_supplied_reviewer_field(self):
        from app.routers.marketplace import ReviewRequest
        self.assertNotIn("reviewer", ReviewRequest.model_fields)

    def test_publish_request_author_comes_from_context_not_client(self):
        import inspect
        from app.routers import marketplace
        source = inspect.getsource(marketplace.publish_listing)
        self.assertIn("ctx.user_email", source)

    def test_ownership_check_exists_for_update_and_delete(self):
        """Closes a gap found during implementation: RBAC permission alone
        isn't ownership — once marketplace_items.owner_organization_id
        exists, an org with marketplace:publish/manage must not be able to
        edit or delete another org's listing."""
        import inspect
        from app.routers import marketplace
        for name in ("update_listing", "delete_listing"):
            source = inspect.getsource(getattr(marketplace, name))
            self.assertIn("_assert_owns", source, f"{name} must check listing ownership")


if __name__ == "__main__":
    unittest.main()
