import re
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.filters.schema import FilterNode


HEX_64_REGEX = re.compile(r"^[0-9a-fA-F]{64}$")


class QuarantineFilteredAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["quarantine_filtered"]
    root_ids: list[int]
    filter: FilterNode | None = None

    @field_validator("root_ids", mode="before")
    @classmethod
    def validate_root_ids(cls, v: Any) -> list[int]:
        if not isinstance(v, list) or len(v) == 0:
            raise ValueError("root_ids must be a non-empty list of integers")
        if len(v) > 16:
            raise ValueError("root_ids must contain at most 16 distinct root IDs")

        seen = set()
        clean_ids: list[int] = []
        for item in v:
            # Reject booleans (bool is a subclass of int in Python)
            if isinstance(item, bool) or not isinstance(item, int):
                raise ValueError("root_ids items must be strict integers, not booleans or other types")
            if item <= 0:
                raise ValueError("root_ids items must be strictly positive integers")
            if item in seen:
                raise ValueError(f"Duplicate root ID detected: {item}")
            seen.add(item)
            clean_ids.append(item)

        return clean_ids


class BatchUtilityPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: QuarantineFilteredAction
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=500)


class BatchUtilityGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: QuarantineFilteredAction
    expected_preview_digest: str

    @field_validator("expected_preview_digest")
    @classmethod
    def validate_digest(cls, v: Any) -> str:
        if not isinstance(v, str) or not HEX_64_REGEX.match(v):
            raise ValueError("expected_preview_digest must be a 64-character hexadecimal string")
        return v.lower()


class BatchUtilityPreviewRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_path: str
    target_path: str | None = None
    index_root_id: int
    index_root_path: str
    relative_path: str
    object_type: Literal["file", "directory", "symlink", "unsupported", "missing"]
    decision: Literal["QUARANTINE", "SAFETY_EXCLUDED", "SKIPPED"]
    reason_code: str | None = None
    reason: str | None = None
    size: int = 0
    protected_dir: str | None = None


class BatchUtilityPreviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    utility_action: Literal["quarantine_filtered"]
    utility_engine_version: int
    preview_source: Literal["index-readonly-safety"]
    live_filesystem_verified: Literal[False]
    matched_count: int
    matched_bytes: int
    candidate_count: int
    candidate_bytes: int
    planned_operations_count: int
    skipped_count: int
    safety_excluded_count: int
    blocking_conflict_count: int
    expected_reclaim_bytes: int
    action_config_digest: str
    source_snapshot_digest: str
    preview_digest: str
    effective_safety_policy: dict[str, Any]
    page: int
    page_size: int
    total_pages: int
    items: list[BatchUtilityPreviewRow]
