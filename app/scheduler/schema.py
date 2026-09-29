from __future__ import annotations

import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.scheduler.cron import parse_cron_expression, resolve_scheduler_timezone


class SchedulerValidationError(ValueError):
    pass


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class IndexRootScheduleTarget(_StrictModel):
    type: Literal["index_root"] = "index_root"
    root_id: int = Field(gt=0)


class FclonesScanScheduleTarget(_StrictModel):
    type: Literal["fclones_scan"] = "fclones_scan"
    roots: list[str] = Field(min_length=1, max_length=100)
    isolate: bool = False
    min_size: str | None = Field(default=None, max_length=128)
    name_patterns: list[str] | None = Field(default=None, max_length=100)
    exclude_patterns: list[str] | None = Field(default=None, max_length=100)

    @field_validator("roots")
    @classmethod
    def validate_roots(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values]
        if any(not value for value in cleaned):
            raise ValueError("roots must contain non-empty strings")
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("roots must be unique")
        return cleaned

    @field_validator("name_patterns", "exclude_patterns")
    @classmethod
    def validate_patterns(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        cleaned = [value.strip() for value in values]
        if any(not value for value in cleaned):
            raise ValueError("patterns must contain non-empty strings")
        return cleaned


class MediaAnalysisScheduleTarget(_StrictModel):
    type: Literal["media_analysis"] = "media_analysis"
    root_keys: list[str] = Field(min_length=1, max_length=100)

    @field_validator("root_keys")
    @classmethod
    def validate_root_keys(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values]
        if any(not value for value in cleaned):
            raise ValueError("root_keys must contain non-empty strings")
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("root_keys must be unique")
        return cleaned


class MediaIntegrityVerificationScheduleTarget(_StrictModel):
    type: Literal["media_integrity_verification"] = "media_integrity_verification"
    root_keys: list[str] = Field(min_length=1, max_length=100)

    @field_validator("root_keys")
    @classmethod
    def validate_root_keys(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values]
        if any(not value for value in cleaned):
            raise ValueError("root_keys must contain non-empty strings")
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("root_keys must be unique")
        return cleaned


ScheduleTarget = Annotated[
    IndexRootScheduleTarget
    | FclonesScanScheduleTarget
    | MediaAnalysisScheduleTarget
    | MediaIntegrityVerificationScheduleTarget,
    Field(discriminator="type"),
]


class ScheduleCreate(_StrictModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=2000)
    enabled: bool = True
    target: ScheduleTarget
    cron_expression: str = Field(min_length=1, max_length=128)
    timezone: str = Field(min_length=1, max_length=64)
    overlap_policy: Literal["skip_if_active"] = "skip_if_active"
    missed_run_policy: Literal["skip"] = "skip"

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("name must not be blank")
        return cleaned

    @field_validator("cron_expression")
    @classmethod
    def validate_cron(cls, value: str) -> str:
        return parse_cron_expression(value).source

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        resolve_scheduler_timezone(value)
        return value


class ScheduleUpdate(_StrictModel):
    expected_revision: int = Field(gt=0)
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2000)
    enabled: bool | None = None
    target: ScheduleTarget | None = None
    cron_expression: str | None = Field(default=None, min_length=1, max_length=128)
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    overlap_policy: Literal["skip_if_active"] | None = None
    missed_run_policy: Literal["skip"] | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("name must not be blank")
        return cleaned

    @field_validator("cron_expression")
    @classmethod
    def validate_cron(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return parse_cron_expression(value).source

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        resolve_scheduler_timezone(value)
        return value


def canonical_target_json(target: ScheduleTarget) -> str:
    return json.dumps(
        target.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
