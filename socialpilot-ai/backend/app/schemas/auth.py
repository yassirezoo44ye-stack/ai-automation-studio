from __future__ import annotations

import re

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.schemas.organization import OrganizationMembership
from app.schemas.user import UserPublic

_PASSWORD_MIN_LEN = 8


def _validate_password_strength(password: str) -> str:
    if len(password) < _PASSWORD_MIN_LEN:
        raise ValueError(f"Password must be at least {_PASSWORD_MIN_LEN} characters long")
    if not re.search(r"[A-Za-z]", password):
        raise ValueError("Password must contain at least one letter")
    if not re.search(r"\d", password):
        raise ValueError("Password must contain at least one digit")
    return password


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=_PASSWORD_MIN_LEN, max_length=256)
    full_name: str = Field(min_length=1, max_length=255)
    organization_name: str | None = Field(default=None, max_length=255)

    @field_validator("password")
    @classmethod
    def _check_password(cls, v: str) -> str:
        return _validate_password_strength(v)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=_PASSWORD_MIN_LEN, max_length=256)

    @field_validator("new_password")
    @classmethod
    def _check_password(cls, v: str) -> str:
        return _validate_password_strength(v)


class AccessTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    csrf_token: str
    user: UserPublic
    organizations: list[OrganizationMembership]


class MeResponse(BaseModel):
    user: UserPublic
    organizations: list[OrganizationMembership]
