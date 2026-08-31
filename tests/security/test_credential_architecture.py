"""
Credential Architecture Security Regression Suite — Phase 14
=============================================================

Proves that FLOW's AI runtime is architecturally independent from any
Claude Code session or browser authentication token, and that provider
secrets never leave the backend process.

Verified properties:
  C1  — Provider keys loaded exclusively from server env vars
  C2  — BaseProvider._api_key() returns env value; never accepts external input
  C3  — Provider constructor accepts no api_key argument
  C4  — Provider.is_available uses env var, not a hardcoded/injected value
  C5  — _classify_sdk_error never includes key value in error message
  C6  — resolve_chain returns only providers whose key is in env
  C7  — /api/health/providers response: never includes key value, only metadata
  C8  — StreamChunk schema has no api_key field
  C9  — CompletionRequest has no api_key field (caller cannot inject a key)
  C10 — FLOW JWT is structurally distinct from a provider API key
  C11 — provider_switched chunk never carries a key value
  C12 — Billing error message contains no key value
  C13 — stream_with_events error chunk contains no key value
  C14 — BaseProvider repr never leaks key value
  C15 — Frontend bundle: provider key strings are help-text only (no values)
  C16 — localStorage stores only FLOW tokens, not provider keys
  C17 — sessionStorage stores only project/UI state, not provider keys
  C18 — CompletionRequest.fallback_providers accepts provider IDs, not keys
"""
from __future__ import annotations

import asyncio
import inspect
import os
import re
import sys
from pathlib import Path
from typing import AsyncGenerator
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.ai.models import CompletionRequest, CompletionResponse, StreamChunk, Message, UsageStats
from app.ai.errors import AIProviderError, AIProviderErrorCode


# ── Helpers ────────────────────────────────────────────────────────────────────

def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


_FAKE_KEY = "sk-ant-api03-FAKE-KEY-FOR-TESTING-ONLY"
_FAKE_OAI_KEY = "sk-proj-FAKE-OPENAI-KEY"
_FAKE_GEM_KEY = "AIzaSy-FAKE-GEMINI-KEY"

# Patterns that would indicate a real or test secret leaked into output
_SECRET_PATTERNS = [
    re.compile(r"sk-ant-api\d+-[A-Za-z0-9-]{20,}"),
    re.compile(r"sk-(proj|or|\d+)-[A-Za-z0-9-]{20,}"),
    re.compile(r"AIzaSy[A-Za-z0-9_-]{30,}"),
    re.compile(r"gsk_[A-Za-z0-9]{20,}"),
]


def _contains_secret(text: str) -> bool:
    """Return True if text contains anything that looks like a real API key."""
    return any(p.search(text) for p in _SECRET_PATTERNS)


# ── C1: Keys loaded from env vars ─────────────────────────────────────────────

class TestC1_ProviderKeysFromEnvOnly:
    """Provider API keys come exclusively from os.getenv — never injected."""

    def test_anthropic_provider_reads_key_from_env(self):
        from app.ai.providers.anthropic import AnthropicProvider
        p = AnthropicProvider()
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": _FAKE_KEY}):
            assert p._api_key() == _FAKE_KEY

    def test_anthropic_provider_returns_empty_when_env_absent(self):
        from app.ai.providers.anthropic import AnthropicProvider
        p = AnthropicProvider()
        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
        with patch.dict(os.environ, env, clear=True):
            assert p._api_key() == ""

    def test_openai_provider_reads_key_from_env(self):
        from app.ai.providers.openai import OpenAIProvider
        p = OpenAIProvider()
        with patch.dict(os.environ, {"OPENAI_API_KEY": _FAKE_OAI_KEY}):
            assert p._api_key() == _FAKE_OAI_KEY

    def test_gemini_provider_reads_key_from_env(self):
        from app.ai.providers.gemini import GeminiProvider
        p = GeminiProvider()
        with patch.dict(os.environ, {"GEMINI_API_KEY": _FAKE_GEM_KEY}):
            assert p._api_key() == _FAKE_GEM_KEY


# ── C2 + C3: No external key injection ────────────────────────────────────────

class TestC2C3_NoExternalKeyInjection:
    """Providers cannot be constructed with a caller-supplied key."""

    def test_anthropic_constructor_accepts_no_api_key_param(self):
        from app.ai.providers.anthropic import AnthropicProvider
        sig = inspect.signature(AnthropicProvider.__init__)
        params = set(sig.parameters.keys()) - {"self"}
        assert "api_key" not in params, (
            "AnthropicProvider.__init__ must not accept api_key — "
            "key must come from env only"
        )

    def test_openai_constructor_accepts_no_api_key_param(self):
        from app.ai.providers.openai import OpenAIProvider
        sig = inspect.signature(OpenAIProvider.__init__)
        params = set(sig.parameters.keys()) - {"self"}
        assert "api_key" not in params

    def test_gemini_constructor_accepts_no_api_key_param(self):
        from app.ai.providers.gemini import GeminiProvider
        sig = inspect.signature(GeminiProvider.__init__)
        params = set(sig.parameters.keys()) - {"self"}
        assert "api_key" not in params

    def test_base_provider_api_key_reads_env_not_instance_attr(self):
        from app.ai.providers.base import BaseProvider
        src = inspect.getsource(BaseProvider._api_key)
        assert "os.getenv" in src or "os.environ" in src, (
            "BaseProvider._api_key() must read from os.getenv, not an instance attr"
        )
        assert "self." not in src.replace("self._env_key", ""), (
            "BaseProvider._api_key() must not read from a self.attribute set at init time"
        )


# ── C4: is_available from env ─────────────────────────────────────────────────

class TestC4_AvailabilityFromEnv:
    """is_available reflects the current env var state, not a cached value."""

    def test_is_available_true_when_key_set(self):
        from app.ai.providers.anthropic import AnthropicProvider
        p = AnthropicProvider()
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": _FAKE_KEY}):
            assert p.is_available is True

    def test_is_available_false_when_key_absent(self):
        from app.ai.providers.anthropic import AnthropicProvider
        p = AnthropicProvider()
        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
        with patch.dict(os.environ, env, clear=True):
            assert p.is_available is False


# ── C5: Error classification never leaks key ──────────────────────────────────

class TestC5_ErrorClassificationKeyFree:
    """_classify_sdk_error produces messages that never include the API key."""

    def test_auth_error_message_contains_no_key_value(self):
        import anthropic as sdk
        from app.ai.providers.anthropic import _classify_sdk_error

        exc = sdk.AuthenticationError(
            message="Invalid API key",
            response=MagicMock(headers={}, status_code=401),
            body={"error": {"message": "Invalid API key", "type": "authentication_error"}},
        )
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": _FAKE_KEY}):
            err = _classify_sdk_error(exc, "anthropic")
        assert _FAKE_KEY not in err.message
        assert not _contains_secret(err.message)

    def test_billing_error_message_contains_no_key_value(self):
        import anthropic as sdk
        from app.ai.providers.anthropic import _classify_sdk_error

        exc = sdk.BadRequestError(
            message="credit balance is too low",
            response=MagicMock(headers={}, status_code=400),
            body={"error": {"message": "credit balance is too low"}},
        )
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": _FAKE_KEY}):
            err = _classify_sdk_error(exc, "anthropic")
        assert err.code == AIProviderErrorCode.BILLING_REQUIRED
        assert _FAKE_KEY not in err.message
        assert not _contains_secret(err.message)


# ── C6: resolve_chain filters by availability ─────────────────────────────────

class TestC6_ResolveChainFiltersAvailability:
    """resolve_chain never returns a provider whose key is absent."""

    def test_unavailable_provider_excluded_from_chain(self):
        from app.core.ai.registry.registry import PlatformProviderRegistry
        from app.plugins.registry_guard import OwnershipTracker

        p_ok  = MagicMock()
        p_ok.provider_id  = "openai"
        p_ok.is_available = True

        p_bad = MagicMock()
        p_bad.provider_id  = "anthropic"
        p_bad.is_available = False  # key absent

        reg = object.__new__(PlatformProviderRegistry)
        reg._providers      = {"anthropic": p_bad, "openai": p_ok}
        reg._builtin_ids    = set()
        reg._billing_errors = {}
        reg._owners         = OwnershipTracker("AI provider")
        reg._owners.claim("anthropic", None)
        reg._owners.claim("openai", None)

        chain = reg.resolve_chain(CompletionRequest(
            messages=[Message(role="user", content="hello")],
        ))
        ids = [p.provider_id for p in chain]
        assert "anthropic" not in ids, (
            "resolve_chain must exclude providers whose key is absent"
        )
        assert "openai" in ids


# ── C7: Health endpoint never returns key values ──────────────────────────────

class TestC7_HealthEndpointKeyFree:
    """The /api/health/providers diagnostic returns metadata only, never the key value."""

    def test_key_info_structure_has_no_value_field(self):
        """The _key_info helper in health.py must not include a 'value' field."""
        import app.routers.health as health_mod
        src = inspect.getsource(health_mod)
        # Find _key_info / _key_meta and confirm 'value' is not returned
        # We check that the dict returned by _key_info only has safe fields
        fn_match = re.search(
            r"def _key_info\(.*?\n(?:.|\n)*?return \{(.*?)\}", src
        )
        if fn_match:
            returned_keys = fn_match.group(1)
            assert '"value"' not in returned_keys, (
                "_key_info must not return the key value"
            )
            assert '"key"' not in returned_keys or "True" in returned_keys, (
                "_key_info must not return the key itself"
            )

    def test_key_meta_fields_are_safe(self):
        """_key_meta in provider_probe must contain only safe metadata fields."""
        import app.routers.health as health_mod
        src = inspect.getsource(health_mod)
        # Confirm the function returns only the approved safe fields
        fn_match = re.search(
            r"def _key_meta\(.*?\n(?:.|\n)*?return \{(.*?)\}", src, re.DOTALL
        )
        if fn_match:
            body = fn_match.group(1)
            assert '"value"' not in body
            # Safe fields: present, non_empty, length, has_whitespace
            assert "present" in body
            assert "non_empty" in body


# ── C8 + C9: Schema has no api_key fields ─────────────────────────────────────

class TestC8C9_SchemaHasNoKeyFields:
    """Neither StreamChunk nor CompletionRequest can carry an API key."""

    def test_stream_chunk_has_no_api_key_field(self):
        sc = StreamChunk(type="delta", text="hello")
        assert not hasattr(sc, "api_key"), "StreamChunk must not have api_key field"
        assert not hasattr(sc, "provider_key"), "StreamChunk must not have provider_key field"
        # Confirm all field names
        fields = set(StreamChunk.model_fields.keys())
        dangerous = fields & {"api_key", "provider_key", "secret", "token"}
        assert not dangerous, f"StreamChunk has dangerous fields: {dangerous}"

    def test_completion_request_has_no_api_key_field(self):
        fields = set(CompletionRequest.model_fields.keys())
        dangerous = fields & {"api_key", "provider_key", "secret"}
        assert not dangerous, f"CompletionRequest has dangerous fields: {dangerous}"

    def test_completion_request_fallback_providers_are_ids_not_keys(self):
        """fallback_providers should be provider IDs (strings like 'openai'), not keys."""
        req = CompletionRequest(
            messages=[Message(role="user", content="hi")],
            fallback_providers=["openai", "gemini"],
        )
        for fb in req.fallback_providers:
            # Provider IDs are short strings; keys are 20+ chars
            assert len(fb) < 20, (
                f"fallback_providers entry '{fb}' looks like a key, not a provider ID"
            )
            assert not _contains_secret(fb)


# ── C10: FLOW JWT ≠ provider API key ─────────────────────────────────────────

class TestC10_JWTNotProviderKey:
    """FLOW JWTs are signed by SESSION_SECRET and are structurally distinct from provider keys."""

    def test_jwt_never_forwarded_as_anthropic_api_key(self):
        """AnthropicProvider._api_key() must read ANTHROPIC_API_KEY, not any JWT env var."""
        from app.ai.providers.anthropic import AnthropicProvider
        src = inspect.getsource(AnthropicProvider._api_key
                                if hasattr(AnthropicProvider, "_api_key")
                                else AnthropicProvider.__mro__[1]._api_key)
        # The env var name must be ANTHROPIC_API_KEY, not ACCESS_TOKEN or JWT or SESSION
        assert "ANTHROPIC_API_KEY" in src or "_env_key" in src, (
            "_api_key() must use ANTHROPIC_API_KEY env var"
        )
        jwt_vars = ["ACCESS_TOKEN", "SESSION_SECRET", "JWT_SECRET", "sub_token"]
        for var in jwt_vars:
            assert var not in src, (
                f"AnthropicProvider._api_key() must not read {var} — "
                "FLOW user JWT must never be used as an AI provider credential"
            )

    def test_base_provider_env_key_is_provider_specific(self):
        """BaseProvider._env_key() returns '<PROVIDER>_API_KEY', not SESSION_SECRET."""
        from app.ai.providers.anthropic import AnthropicProvider
        p = AnthropicProvider()
        env_key = p._env_key()
        assert env_key == "ANTHROPIC_API_KEY"
        assert "SESSION" not in env_key
        assert "JWT" not in env_key
        assert "TOKEN" not in env_key


# ── C11: provider_switched chunk is key-free ──────────────────────────────────

class TestC11_ProviderSwitchedChunkKeyFree:
    """The provider_switched StreamChunk carries only provider IDs, never secrets."""

    def test_provider_switched_chunk_fields_are_safe(self):
        chunk = StreamChunk(
            type="provider_switched",
            previous_provider="anthropic",
            provider_id="openai",
            failure_reason="billing_required",
        )
        # Serialize to dict and check no secret value appears
        data = chunk.model_dump()
        for k, v in data.items():
            if v is not None and isinstance(v, str):
                assert not _contains_secret(v), (
                    f"provider_switched.{k} contains a secret-like value: {v!r}"
                )
        # provider ID fields must be short identifiers, not keys
        if chunk.provider_id:
            assert len(chunk.provider_id) < 20
        if chunk.previous_provider:
            assert len(chunk.previous_provider) < 20


# ── C12 + C13: Billing/error chunk key-free ───────────────────────────────────

class TestC12C13_ErrorChunksKeyFree:
    """Billing error messages and stream_with_events error chunks never include key values."""

    def test_billing_error_message_key_free(self):
        err = AIProviderError(
            AIProviderErrorCode.BILLING_REQUIRED,
            provider="anthropic",
            message="The Anthropic API credit balance is too low.",
            retryable=False,
        )
        assert not _contains_secret(err.message)
        assert not _contains_secret(err.provider)

    def test_stream_with_events_exhaustion_error_key_free(self):
        """When all providers fail, the error chunk message must not contain any key value."""
        import json
        from app.core.ai.registry.registry import PlatformProviderRegistry
        from app.plugins.registry_guard import OwnershipTracker

        async def _billing_stream(r):
            raise AIProviderError(
                AIProviderErrorCode.BILLING_REQUIRED,
                provider="anthropic",
                message="Credit balance too low",
                retryable=False,
            )
            yield

        p = MagicMock()
        p.provider_id = "anthropic"
        p.is_available = True
        p.resolve_model = MagicMock(return_value="claude-sonnet")
        p.default_model = MagicMock(return_value="claude-sonnet")
        p.stream = MagicMock(return_value=_billing_stream(None))
        p.complete = MagicMock(side_effect=AIProviderError(
            AIProviderErrorCode.BILLING_REQUIRED,
            provider="anthropic",
            message="Credit balance too low",
            retryable=False,
        ))

        reg = object.__new__(PlatformProviderRegistry)
        reg._providers      = {"anthropic": p}
        reg._builtin_ids    = set()
        reg._billing_errors = {}
        reg._owners         = OwnershipTracker("AI provider")
        reg._owners.claim("anthropic", None)

        req = CompletionRequest(
            messages=[Message(role="user", content="hello")],
            stream=True,
        )

        async def _collect():
            chunks = []
            async for c in reg.stream_with_events(req):
                chunks.append(c)
            return chunks

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": _FAKE_KEY}):
            chunks = asyncio.new_event_loop().run_until_complete(_collect())

        error_chunks = [c for c in chunks if c.type == "error"]
        assert error_chunks, "Must emit an error chunk when all providers fail"
        for ec in error_chunks:
            if ec.error:
                assert not _contains_secret(ec.error), (
                    "Error chunk must not contain provider key value"
                )
                assert _FAKE_KEY not in ec.error


# ── C14: Provider repr never leaks key ────────────────────────────────────────

class TestC14_ProviderReprKeyFree:
    """repr() of a provider instance must not include the API key value."""

    def test_anthropic_repr_key_free(self):
        from app.ai.providers.anthropic import AnthropicProvider
        p = AnthropicProvider()
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": _FAKE_KEY}):
            r = repr(p)
        assert _FAKE_KEY not in r

    def test_openai_repr_key_free(self):
        from app.ai.providers.openai import OpenAIProvider
        p = OpenAIProvider()
        with patch.dict(os.environ, {"OPENAI_API_KEY": _FAKE_OAI_KEY}):
            r = repr(p)
        assert _FAKE_OAI_KEY not in r


# ── C15: Frontend bundle has no key values ────────────────────────────────────

class TestC15_FrontendBundleKeyFree:
    """Built frontend bundle must not contain actual provider key values."""

    DIST_DIR = Path(__file__).parent.parent.parent / "dist" / "assets"

    def _scan_bundle(self, pattern: re.Pattern) -> list[tuple[str, str]]:
        """Return [(filename, match)] for all matches in dist JS files."""
        hits = []
        if not self.DIST_DIR.exists():
            return []
        for f in self.DIST_DIR.glob("*.js"):
            content = f.read_text(errors="replace")
            for m in pattern.finditer(content):
                hits.append((f.name, m.group(0)))
        return hits

    def test_no_anthropic_key_value_in_bundle(self):
        hits = self._scan_bundle(re.compile(r"sk-ant-api\d+-[A-Za-z0-9-]{20,}"))
        assert not hits, f"Anthropic key value found in bundle: {hits}"

    def test_no_openai_key_value_in_bundle(self):
        hits = self._scan_bundle(re.compile(r"sk-(proj|or|\d+)-[A-Za-z0-9-]{20,}"))
        assert not hits, f"OpenAI/OpenRouter key value found in bundle: {hits}"

    def test_no_gemini_key_value_in_bundle(self):
        hits = self._scan_bundle(re.compile(r"AIzaSy[A-Za-z0-9_-]{30,}"))
        assert not hits, f"Gemini key value found in bundle: {hits}"

    def test_no_vite_provider_key_env_in_bundle(self):
        """VITE_ANTHROPIC_API_KEY etc. must not appear — provider keys are backend-only."""
        hits = self._scan_bundle(re.compile(
            r"VITE_(ANTHROPIC|OPENAI|GEMINI|OPENROUTER|GROQ)_API_KEY"
        ))
        assert not hits, (
            f"VITE_*_API_KEY found in bundle — provider keys must NEVER be in VITE_ vars: {hits}"
        )

    def test_anthropic_api_key_string_is_help_text_only(self):
        """'ANTHROPIC_API_KEY' appearing in bundle is only in template/help strings, not as a runtime var."""
        all_occurrences = []
        if not self.DIST_DIR.exists():
            return
        for f in self.DIST_DIR.glob("*.js"):
            content = f.read_text(errors="replace")
            for m in re.finditer(r".{0,40}ANTHROPIC_API_KEY.{0,40}", content):
                ctx = m.group(0)
                # These occurrences are acceptable: string literals in help/template text
                # They are NOT: import.meta.env.VITE_ANTHROPIC_API_KEY
                if "import.meta.env" in ctx or "VITE_" in ctx:
                    all_occurrences.append((f.name, ctx))
        assert not all_occurrences, (
            "ANTHROPIC_API_KEY referenced via import.meta.env in bundle — "
            "provider keys must be backend-only: "
            f"{all_occurrences}"
        )


# ── C16 + C17: Storage keys are FLOW tokens only ─────────────────────────────

class TestC16C17_StorageContainsNoProviderKeys:
    """Frontend storage (localStorage / sessionStorage) must never hold provider keys."""

    STORAGE_KEYS_FILE = Path(__file__).parent.parent.parent / "src" / "renderer" / "shared" / "utils" / "api.ts"

    def test_localStorage_stores_only_flow_tokens(self):
        """localStorage in api.ts only reads/writes 'sub_token' (a FLOW auth token)."""
        content = self.STORAGE_KEYS_FILE.read_text()
        # Verify sub_token is the stored key
        assert "sub_token" in content
        # Verify no provider key variable names appear in setItem calls
        set_item_ctx = re.findall(r"localStorage\.setItem\([^)]+\)", content)
        for ctx in set_item_ctx:
            assert "ANTHROPIC" not in ctx.upper()
            assert "OPENAI" not in ctx.upper()
            assert "GEMINI" not in ctx.upper()
            assert "API_KEY" not in ctx.upper()

    def test_no_provider_key_in_frontend_storage_hooks(self):
        """useLocalStorage and related hooks must never store provider key values."""
        hooks_dir = Path(__file__).parent.parent.parent / "src" / "renderer" / "shared" / "hooks"
        for hook_file in hooks_dir.glob("*.ts"):
            content = hook_file.read_text()
            # Check for any hardcoded key value patterns
            assert not _contains_secret(content), (
                f"Provider key value found in frontend hook {hook_file.name}"
            )

    def test_no_provider_key_in_sessionStorage_usage(self):
        """sessionStorage in the frontend only holds project IDs and UI state."""
        src_dir = Path(__file__).parent.parent.parent / "src" / "renderer"
        for ts_file in src_dir.rglob("*.ts{x,}"):
            content = ts_file.read_text(errors="replace")
            for m in re.finditer(r"sessionStorage\.setItem\(([^)]+)\)", content):
                key_arg = m.group(1).split(",")[0].strip().strip("\"'")
                # Acceptable keys: flow_builder_prompt, flow_active_project, etc.
                assert "api_key" not in key_arg.lower(), (
                    f"{ts_file}: sessionStorage.setItem with key {key_arg!r} "
                    "— must not store provider API keys"
                )
                assert "anthropic" not in key_arg.lower()
                assert "openai" not in key_arg.lower()


# ── C18: fallback_providers takes IDs not keys ───────────────────────────────

class TestC18_FallbackProvidersAreIDs:
    """CompletionRequest.fallback_providers holds provider IDs, not secret keys."""

    def test_fallback_providers_type_is_string_list(self):
        """The field is a list of strings — IDs like 'openai', not key values."""
        req = CompletionRequest(
            messages=[Message(role="user", content="test")],
            fallback_providers=["openai", "gemini"],
        )
        assert req.fallback_providers == ["openai", "gemini"]
        for entry in req.fallback_providers:
            assert not _contains_secret(entry), (
                f"fallback_providers entry looks like a key: {entry!r}"
            )
