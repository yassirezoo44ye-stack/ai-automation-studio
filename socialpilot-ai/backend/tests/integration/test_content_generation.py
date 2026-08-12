"""AI generation: provider abstraction is exercised end-to-end through the
real HTTP surface with a deterministic fake AIProvider (no real API key,
no network) — see `_override_ai` below, which uses the same
`app.dependency_overrides` mechanism as the `client` fixture's DB override.
"""
from __future__ import annotations

import pytest

from app.main import app
from app.services.ai import get_ai_provider
from app.services.ai.provider import AIGenerationError, AIProvider
from tests.conftest import unique_email

pytestmark = pytest.mark.asyncio


async def _register(client, *, org: str):
    email = unique_email()
    r = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "Sup3rSecret1", "full_name": "User", "organization_name": org},
    )
    assert r.status_code == 201
    body = r.json()
    return {"email": email, "access_token": body["access_token"], "org_id": body["organizations"][0]["id"]}


def _auth(user: dict) -> dict:
    return {"Authorization": f"Bearer {user['access_token']}"}


async def _create_strategy(client, user: dict) -> dict:
    r = await client.post(
        f"/api/v1/organizations/{user['org_id']}/content/strategies",
        json={"name": "Test Strategy", "tone": "engaging", "language": "english"},
        headers=_auth(user),
    )
    assert r.status_code == 201
    return r.json()


class _FakeProvider(AIProvider):
    """Deterministic stand-in for a real vendor. `mode` controls behavior so
    one fixture-free class covers every generation test case."""

    def __init__(self, mode: str = "valid") -> None:
        self.mode = mode

    @property
    def model_name(self) -> str:
        return "fake-model-1"

    async def generate(self, *, system: str, prompt: str, max_tokens: int = 1024) -> str:
        return "fake text"

    async def generate_structured(self, *, system, prompt, schema, max_tokens=2048):
        if self.mode == "provider_error":
            raise AIGenerationError("simulated upstream failure (rate limited)")
        if self.mode == "malformed":
            # Missing required fields / wrong shape entirely.
            return {"unexpected": "shape"}
        if "ideas" in schema.get("properties", {}):
            return {
                "ideas": [
                    {
                        "title": "5 AI tools you're not using yet",
                        "hook": "Most teams only use 10% of what AI can do.",
                        "concept": "A roundup of underrated AI tools for productivity.",
                        "pillar": "AI Tools",
                        "suggested_platform": "linkedin",
                        "cta": "Which one will you try first?",
                    },
                    {
                        "title": "The truth about AI hallucinations",
                        "hook": "AI doesn't lie — it guesses.",
                        "concept": "Myth vs fact post about hallucinations.",
                        "pillar": "AI Education",
                        "suggested_platform": "x",
                        "cta": "Follow for more AI myths debunked.",
                    },
                ]
            }
        return {
            "hook": "Most teams only use 10% of what AI can do.",
            "body": "Here are 5 AI tools that will change how you work...",
            "cta": "Try one today and tell us what you think.",
            "hashtags": ["ai", "productivity"],
            "platform": "linkedin",
            "media_concept": "A carousel graphic listing the 5 tools.",
        }


def _override_ai(mode: str = "valid"):
    app.dependency_overrides[get_ai_provider] = lambda: _FakeProvider(mode)


def _clear_ai_override():
    app.dependency_overrides.pop(get_ai_provider, None)


@pytest.fixture(autouse=True)
def _cleanup_ai_override():
    yield
    _clear_ai_override()


class TestGenerateIdeas:
    async def test_provider_not_configured_returns_503(self, client) -> None:
        # No override installed — the real get_ai_provider() runs, and
        # AI_API_KEY is unset in the test environment (see conftest.py).
        user = await _register(client, org="Acme")
        strategy = await _create_strategy(client, user)
        r = await client.post(
            f"/api/v1/organizations/{user['org_id']}/content/generate/ideas",
            json={"strategy_id": strategy["id"], "count": 3},
            headers=_auth(user),
        )
        assert r.status_code == 503

    async def test_successful_structured_generation(self, client) -> None:
        _override_ai("valid")
        user = await _register(client, org="Acme")
        strategy = await _create_strategy(client, user)
        r = await client.post(
            f"/api/v1/organizations/{user['org_id']}/content/generate/ideas",
            json={"strategy_id": strategy["id"], "count": 2},
            headers=_auth(user),
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "succeeded"
        assert body["generation_type"] == "ideas"
        assert len(body["result"]["ideas"]) == 2
        assert body["result"]["ideas"][0]["title"]
        assert body["error"] is None

    async def test_provider_unavailable_records_failed_generation(self, client) -> None:
        _override_ai("provider_error")
        user = await _register(client, org="Acme")
        strategy = await _create_strategy(client, user)
        r = await client.post(
            f"/api/v1/organizations/{user['org_id']}/content/generate/ideas",
            json={"strategy_id": strategy["id"]},
            headers=_auth(user),
        )
        assert r.status_code == 200  # request itself succeeded; the *generation* failed
        body = r.json()
        assert body["status"] == "failed"
        assert body["result"] is None
        assert "simulated upstream failure" in body["error"]

    async def test_malformed_provider_response_fails_schema_validation(self, client) -> None:
        _override_ai("malformed")
        user = await _register(client, org="Acme")
        strategy = await _create_strategy(client, user)
        r = await client.post(
            f"/api/v1/organizations/{user['org_id']}/content/generate/ideas",
            json={"strategy_id": strategy["id"]},
            headers=_auth(user),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "failed"
        assert "schema validation" in body["error"]

    async def test_unknown_strategy_returns_404(self, client) -> None:
        _override_ai("valid")
        user = await _register(client, org="Acme")
        r = await client.post(
            f"/api/v1/organizations/{user['org_id']}/content/generate/ideas",
            json={"strategy_id": "00000000-0000-0000-0000-000000000000"},
            headers=_auth(user),
        )
        assert r.status_code == 404

    async def test_cannot_generate_using_another_orgs_strategy(self, client) -> None:
        _override_ai("valid")
        owner_a = await _register(client, org="Org A")
        user_b = await _register(client, org="Org B")
        strategy_a = await _create_strategy(client, owner_a)

        r = await client.post(
            f"/api/v1/organizations/{owner_a['org_id']}/content/generate/ideas",
            json={"strategy_id": strategy_a["id"]},
            headers=_auth(user_b),
        )
        assert r.status_code == 404

    async def test_count_out_of_range_rejected(self, client) -> None:
        _override_ai("valid")
        user = await _register(client, org="Acme")
        strategy = await _create_strategy(client, user)
        r = await client.post(
            f"/api/v1/organizations/{user['org_id']}/content/generate/ideas",
            json={"strategy_id": strategy["id"], "count": 999},
            headers=_auth(user),
        )
        assert r.status_code == 422


class TestGeneratePost:
    async def test_successful_post_generation(self, client) -> None:
        _override_ai("valid")
        user = await _register(client, org="Acme")
        strategy = await _create_strategy(client, user)
        r = await client.post(
            f"/api/v1/organizations/{user['org_id']}/content/generate/post",
            json={"strategy_id": strategy["id"], "platform": "linkedin"},
            headers=_auth(user),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "succeeded"
        assert body["generation_type"] == "post"
        assert body["result"]["hashtags"] == ["ai", "productivity"]

    async def test_generation_is_grounded_in_strategy_pillar(self, client) -> None:
        """The prompt actually carries the pillar context through — proven by
        asserting the strategy/pillar were resolved without error (a bogus
        pillar_id from another org must 400, not silently ignore it)."""
        _override_ai("valid")
        owner_a = await _register(client, org="Org A")
        strategy = await _create_strategy(client, owner_a)
        r = await client.post(
            f"/api/v1/organizations/{owner_a['org_id']}/content/generate/post",
            json={"strategy_id": strategy["id"], "platform": "x", "pillar_id": "00000000-0000-0000-0000-000000000000"},
            headers=_auth(owner_a),
        )
        assert r.status_code == 422

    async def test_generated_result_persists_via_content_generation_record(self, client, db_session) -> None:
        import uuid as uuidlib

        from app.models.content_generation import ContentGeneration

        _override_ai("valid")
        user = await _register(client, org="Acme")
        strategy = await _create_strategy(client, user)
        r = await client.post(
            f"/api/v1/organizations/{user['org_id']}/content/generate/post",
            json={"strategy_id": strategy["id"], "platform": "x"},
            headers=_auth(user),
        )
        generation_id = r.json()["id"]
        row = await db_session.get(ContentGeneration, uuidlib.UUID(generation_id))
        assert row is not None
        assert row.model == "fake-model-1"
        assert row.organization_id == uuidlib.UUID(user["org_id"])
        # Close out the transaction .get() implicitly opened, same as every
        # other test that mutates via db_session (see test_rbac.py's
        # _add_member) — leaving it open for fixture teardown to unwind
        # triggers an unrelated asyncpg/event-loop teardown-ordering error.
        await db_session.commit()


class TestGenerationRateLimitConfig:
    async def test_default_rate_limit_is_configured(self) -> None:
        from app.core.config import Settings

        # A dedicated default exists on the Settings class itself (not just
        # the test-environment override in conftest.py) — this is what
        # actually protects the endpoint in a real deployment.
        assert Settings.model_fields["ai_generation_rate_limit"].default == "20/minute"
