from typing import Literal

from pydantic import BaseModel, Field


class CareerProfile(BaseModel):
    summary: str = Field(default="", max_length=6000)
    roles: list[str] = Field(default_factory=list, max_length=30)
    skills: list[str] = Field(default_factory=list, max_length=60)
    sectors: list[str] = Field(default_factory=list, max_length=30)
    languages: list[str] = Field(default_factory=list, max_length=20)
    cities: list[str] = Field(default_factory=list, max_length=20)
    experience_years: float | None = Field(default=None, ge=0, le=60)
    minimum_monthly_aed: int | None = Field(default=None, ge=0, le=1000000)
    uae_driving_license: bool | None = None


class ImportAlert(BaseModel):
    text: str = Field(min_length=1, max_length=200000)
    source: Literal["linkedin", "indeed", "manual"] = "manual"
    # When the alert parser finds no supported job links, let the AI find
    # the openings in the text instead.
    use_ai: bool = False


class ProfileExtract(BaseModel):
    text: str = Field(min_length=20, max_length=30000)


class FitRequest(BaseModel):
    language: Literal["en", "ar"] = "en"


class JobStatus(BaseModel):
    status: Literal["new", "saved", "applied", "interview", "rejected"]


class ScheduleSettings(BaseModel):
    enabled: bool
    interval_hours: int = Field(default=24, ge=6, le=168)


class OAuthExchange(BaseModel):
    code: str = Field(min_length=1, max_length=4096)
    state: str = Field(min_length=20, max_length=256)
