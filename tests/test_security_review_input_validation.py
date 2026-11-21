"""Request bounds and response/log redaction; no live services or lifespan."""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field, ValidationError

from app.factory import create_app
from app.routers.build import BuildRequest, MAX_BUILD_PROMPT_CHARS, PlanRequest


@pytest.mark.parametrize("model", [PlanRequest, BuildRequest])
@pytest.mark.parametrize("prompt", ["أنشئ تطبيقاً " * 1000, "🚀" * MAX_BUILD_PROMPT_CHARS])
def test_long_build_prompts_preserved(model, prompt):
    assert model(prompt=prompt, **({"project_id": "test-project"} if model is BuildRequest else {})).prompt == prompt


@pytest.mark.parametrize("model", [PlanRequest, BuildRequest])
@pytest.mark.parametrize("prompt", ["", " \n\t", "ع" * (MAX_BUILD_PROMPT_CHARS + 1)])
def test_invalid_build_prompt_rejected(model, prompt):
    with pytest.raises(ValidationError):
        model(prompt=prompt, **({"project_id": "test-project"} if model is BuildRequest else {}))


class SensitiveRequest(BaseModel):
    password: str = Field(max_length=3)


@pytest.fixture
def client():
    app = create_app()

    @app.post("/health/security-review-validation")
    async def validation(body: SensitiveRequest):
        return {"ok": True}

    @app.post("/health/security-review-error")
    async def error():
        raise RuntimeError("secret-token database password /private/source.sql")

    # No context manager: do not run DB/background-worker lifespan.
    return TestClient(app, raise_server_exceptions=False)


def test_validation_does_not_reflect_sensitive_input(client):
    response = client.post("/health/security-review-validation", json={"password": "secret-password"})
    assert response.status_code == 422
    assert "secret-password" not in response.text
    for error in response.json()["errors"]:
        assert set(error) == {"type", "loc", "msg"}


def test_unhandled_error_is_generic_in_response_and_log(client):
    with patch("app.factory.logging.getLogger") as logger:
        response = client.post("/health/security-review-error")
    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}
    assert response.headers["cache-control"] == "no-store"
    logger.return_value.error.assert_called_once()
    logged = str(logger.return_value.error.call_args)
    assert "RuntimeError" in logged
    assert "secret-token" not in logged
    assert "/private/source.sql" not in logged
