"""
PromptEngine — enhanced prompt management.

Wraps app.ai.prompt_store with:
- Preview (render without persisting)
- Validation (check all variables are present)
- Rollback to a previous version
- Category support
- Test execution (render + run against a provider)

Usage::

    engine = PromptEngine(pool)
    rendered = await engine.preview("my-prompt", variables={"name": "Alice"})
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

from app.ai import prompt_store as _store
from app.ai.models import PromptVersion
from app.core.ai.events.bus import bus
from app.core.ai.events.events import PromptSaved

log = logging.getLogger(__name__)

_VAR_RE = re.compile(r"\{\{(\w+)\}\}")


@dataclass
class PromptPreview:
    system:        Optional[str]
    user_template: Optional[str]
    missing_vars:  list[str]     # variables in template but not supplied
    extra_vars:    list[str]     # variables supplied but not in template
    valid:         bool


@dataclass
class PromptTestResult:
    prompt_id:  str
    version:    int
    variables:  dict[str, str]
    rendered_system: Optional[str]
    rendered_user:   Optional[str]
    response:        Optional[str]  # AI response if executed
    success:         bool
    error:           Optional[str] = None


class PromptEngine:
    """
    All prompt operations go through here — never through prompt_store directly
    in new code.
    """

    def __init__(self, pool) -> None:
        self._pool = pool

    # ── Read ──────────────────────────────────────────────────────────────────

    async def get_active(self, prompt_id: str) -> Optional[PromptVersion]:
        return await _store.get_active_version(self._pool, prompt_id)

    async def list_versions(self, prompt_id: str) -> list[PromptVersion]:
        return await _store.list_versions(self._pool, prompt_id)

    # ── Preview (render without persisting) ───────────────────────────────────

    async def preview(
        self,
        prompt_id: str,
        variables: dict[str, str] | None = None,
    ) -> PromptPreview:
        """Render the active version with given variables. Never persists."""
        variables = variables or {}
        version   = await self.get_active(prompt_id)
        if not version:
            return PromptPreview(
                system=None, user_template=None,
                missing_vars=[], extra_vars=list(variables.keys()),
                valid=False,
            )

        declared_vars = set(version.variables)
        supplied_vars = set(variables.keys())
        missing_vars  = sorted(declared_vars - supplied_vars)
        extra_vars    = sorted(supplied_vars - declared_vars)

        rendered_sys, rendered_user = await _store.render(version, variables)

        return PromptPreview(
            system=rendered_sys,
            user_template=rendered_user,
            missing_vars=missing_vars,
            extra_vars=extra_vars,
            valid=len(missing_vars) == 0,
        )

    # ── Validation ────────────────────────────────────────────────────────────

    def validate_template(
        self,
        system:        Optional[str],
        user_template: Optional[str],
        variables:     dict[str, str],
    ) -> PromptPreview:
        """Validate a template without any DB interaction."""
        all_text  = (system or "") + (user_template or "")
        found     = {m.group(1) for m in _VAR_RE.finditer(all_text)}
        supplied  = set(variables.keys())
        missing   = sorted(found - supplied)
        extra     = sorted(supplied - found)

        def sub(text: Optional[str]) -> Optional[str]:
            if not text:
                return text
            return _VAR_RE.sub(lambda m: variables.get(m.group(1), m.group(0)), text)

        return PromptPreview(
            system=sub(system),
            user_template=sub(user_template),
            missing_vars=missing,
            extra_vars=extra,
            valid=len(missing) == 0,
        )

    # ── Write ─────────────────────────────────────────────────────────────────

    async def create(
        self,
        *,
        name:          str,
        slug:          str,
        description:   str = "",
        system:        Optional[str] = None,
        user_template: Optional[str] = None,
        variables:     Optional[list[str]] = None,
        user_id:       Optional[str] = None,
    ) -> str:
        pid = await _store.create_prompt(
            self._pool,
            name=name,
            slug=slug,
            description=description,
            system=system,
            user_template=user_template,
            variables=variables,
            user_id=user_id,
        )
        await bus.emit(PromptSaved(
            prompt_id=pid,
            slug=slug,
            version=1,
            user_id=user_id,
        ))
        return pid

    async def publish_version(
        self,
        prompt_id:     str,
        *,
        system:        Optional[str] = None,
        user_template: Optional[str] = None,
        variables:     Optional[list[str]] = None,
    ) -> int:
        version = await _store.publish_version(
            self._pool, prompt_id,
            system=system,
            user_template=user_template,
            variables=variables,
        )
        await bus.emit(PromptSaved(prompt_id=prompt_id, slug="", version=version))
        return version

    async def rollback(self, prompt_id: str, target_version: int) -> int:
        """
        Activate a historical version.

        Copies that version's content as a new version (so history is preserved).
        """
        all_versions = await self.list_versions(prompt_id)
        target = next((v for v in all_versions if v.version == target_version), None)
        if not target:
            raise ValueError(f"Version {target_version} not found for prompt {prompt_id!r}")

        new_version = await self.publish_version(
            prompt_id,
            system=target.system,
            user_template=target.user_template,
            variables=target.variables,
        )
        log.info(
            "PromptEngine: rolled back prompt %s from v%d to v%d (new v%d)",
            prompt_id, len(all_versions), target_version, new_version,
        )
        return new_version

    # ── Test execution ────────────────────────────────────────────────────────

    async def test(
        self,
        prompt_id:  str,
        variables:  dict[str, str] | None = None,
        *,
        provider_id: Optional[str] = None,
        model:       Optional[str] = None,
    ) -> PromptTestResult:
        """Render the active prompt and optionally run it through an AI provider."""
        from app.ai.models import CompletionRequest, Message, ProviderID
        from app.core.ai.registry.registry import platform_registry

        variables = variables or {}
        version   = await self.get_active(prompt_id)
        if not version:
            return PromptTestResult(
                prompt_id=prompt_id, version=0, variables=variables,
                rendered_system=None, rendered_user=None,
                response=None, success=False,
                error="No active version found",
            )

        rendered_sys, rendered_user = await _store.render(version, variables)

        try:
            req = CompletionRequest(
                messages=[Message(role="user", content=rendered_user or "Hello")],
                system=rendered_sys,
                provider=ProviderID(provider_id) if provider_id else None,
                model=model,
                max_tokens=512,
                temperature=0.7,
            )
            resp, _ = await platform_registry.complete_with_events(req)
            return PromptTestResult(
                prompt_id=prompt_id, version=version.version,
                variables=variables,
                rendered_system=rendered_sys, rendered_user=rendered_user,
                response=resp.content, success=True,
            )
        except Exception as exc:
            return PromptTestResult(
                prompt_id=prompt_id, version=version.version,
                variables=variables,
                rendered_system=rendered_sys, rendered_user=rendered_user,
                response=None, success=False, error=str(exc),
            )
