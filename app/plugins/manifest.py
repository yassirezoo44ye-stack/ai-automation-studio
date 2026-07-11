"""
Plugin manifest — every plugin ships one, validated before it is ever loaded.

Reuses app/marketplace/dependencies.py's MAJOR.MINOR.PATCH version shape
(same regex pattern) and app/marketplace/security.py's ALL_KNOWN_CAPABILITIES
allowlist for required_permissions — no new version or capability logic is
invented here.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.plugins.base import PluginType

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{2,63}$")
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")  # matches dependencies.py's _VERSION_RE exactly


class ManifestValidationError(Exception):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


class PluginDependencySpec(BaseModel):
    plugin_id         : str
    version_constraint: str = "*"
    optional          : bool = False


class PluginManifest(BaseModel):
    id          : str = Field(..., description="Stable, unique plugin identifier")
    name        : str = Field(..., min_length=1, max_length=120)
    version     : str
    author      : str = Field(..., min_length=1, max_length=120)
    description : str = Field(..., min_length=1, max_length=2000)
    category    : PluginType

    dependencies        : list[PluginDependencySpec] = Field(default_factory=list)
    required_permissions: list[str] = Field(default_factory=list)

    min_platform_version: str
    max_platform_version: Optional[str] = None

    entry_point: str = Field(..., description="'module_path:ClassName' resolved after import")
    configuration_schema: dict[str, Any] = Field(default_factory=dict)

    @field_validator("id")
    @classmethod
    def _validate_id(cls, v: str) -> str:
        if not _ID_RE.match(v):
            raise ValueError(
                "id must be 3-64 lowercase alphanumeric/underscore/hyphen characters, "
                "starting with a letter or digit"
            )
        return v

    @field_validator("version", "min_platform_version")
    @classmethod
    def _validate_version(cls, v: str) -> str:
        if not _VERSION_RE.match(v):
            raise ValueError(f"not a MAJOR.MINOR.PATCH version: {v!r}")
        return v

    @field_validator("max_platform_version")
    @classmethod
    def _validate_max_version(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not _VERSION_RE.match(v):
            raise ValueError(f"not a MAJOR.MINOR.PATCH version: {v!r}")
        return v

    @field_validator("entry_point")
    @classmethod
    def _validate_entry_point(cls, v: str) -> str:
        if ":" not in v or not all(v.split(":", 1)):
            raise ValueError("entry_point must be 'module.path:ClassName'")
        return v

    @model_validator(mode="after")
    def _validate_dependencies_not_self(self) -> "PluginManifest":
        for dep in self.dependencies:
            if dep.plugin_id == self.id:
                raise ValueError(f"plugin {self.id!r} cannot depend on itself")
        return self


def parse_manifest(raw: dict[str, Any]) -> PluginManifest:
    """Raises ManifestValidationError with all field errors collected, not
    just the first — so a publisher fixing their manifest.json sees every
    problem in one pass instead of one-at-a-time."""
    try:
        return PluginManifest.model_validate(raw)
    except Exception as exc:
        # pydantic ValidationError has .errors(); anything else (e.g. a
        # plain KeyError from malformed JSON) falls back to str(exc).
        errors = getattr(exc, "errors", None)
        if callable(errors):
            messages = [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in errors()]
        else:
            messages = [str(exc)]
        raise ManifestValidationError(messages) from exc


def validate_permissions(manifest: PluginManifest) -> list[str]:
    """Delegates to the Marketplace phase's already-shipped capability
    allowlist check — returns a list of unknown-capability findings (empty
    if every declared permission is recognized)."""
    from app.marketplace.security import check_permission_manifest
    return check_permission_manifest(manifest.required_permissions)


_JSON_SCHEMA_TYPES: dict[str, type | tuple[type, ...]] = {
    "string": str, "number": (int, float), "integer": int,
    "boolean": bool, "object": dict, "array": list,
}


def validate_config_against_schema(config: dict[str, Any], json_schema: dict[str, Any]) -> list[str]:
    """Hand-rolled validator for the small JSON Schema subset a plugin
    configuration_schema realistically needs: top-level "properties" (each
    with "type" and optionally "enum"), and "required". Deliberately not
    the full jsonschema library — no new pip dependency for the same reason
    Marketplace hand-rolled its version comparator instead of adding
    `packaging`/`semver`; unlike encryption, a type/required-field checker
    is safe and small to hand-roll."""
    if not json_schema:
        return []
    errors: list[str] = []
    properties: dict[str, Any] = json_schema.get("properties", {})
    for key in json_schema.get("required", []):
        if key not in config:
            errors.append(f"missing required field: {key!r}")
    for key, value in config.items():
        prop = properties.get(key)
        if prop is None:
            continue  # unknown fields are allowed (schema isn't necessarily exhaustive)
        expected_type = _JSON_SCHEMA_TYPES.get(prop.get("type", ""))
        if expected_type and not isinstance(value, expected_type):
            errors.append(f"{key!r}: expected type {prop['type']!r}, got {type(value).__name__!r}")
        enum = prop.get("enum")
        if enum and value not in enum:
            errors.append(f"{key!r}: {value!r} is not one of {enum!r}")
    return errors
