from __future__ import annotations

import math
from typing import Any, Literal, Union
from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from app.filters.schema import FilterNode
from app.organizers.profile_validation import (
    DEFAULT_ORGANIZER_CLEANUP_PATTERNS,
    DEFAULT_ORGANIZER_IMAGE_EXTENSIONS,
    DEFAULT_ORGANIZER_MTIME_DELAY_SECONDS,
    DEFAULT_ORGANIZER_MTIME_MODE,
    DEFAULT_ORGANIZER_NUMBERING_MODE,
    DEFAULT_ORGANIZER_NUMBERING_PADDING,
    DEFAULT_ORGANIZER_NUMBERING_START,
    DEFAULT_ORGANIZER_PRESERVE_TAGS,
    DEFAULT_ORGANIZER_RECURSIVE,
    DEFAULT_ORGANIZER_RENAME_TEMPLATE,
    DEFAULT_ORGANIZER_STATISTICS_TEMPLATE,
    DEFAULT_ORGANIZER_VIDEO_EXTENSIONS,
    normalize_preserve_tags,
    validate_and_normalize_image_extensions,
    validate_and_normalize_video_extensions,
    validate_profile_cleanup_patterns,
    validate_profile_name,
    validate_rename_template,
    validate_statistics_template,
)


class BaseStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    type: str


class ScanStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    type: Literal["scan"] = "scan"
    root_ids: list[int] = Field(default_factory=list)
    subpath: str = ""


class FilterStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    type: Literal["filter"] = "filter"
    filter: FilterNode


class RenameStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    type: Literal["rename"] = "rename"
    pattern: str
    replacement: str


class MoveStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    type: Literal["move"] = "move"
    destination_root_id: int
    destination_subpath: str = ""


class TouchStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    type: Literal["touch"] = "touch"
    mtime_ns: int | None = None
    touch_now: bool = True


class QuarantineStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    type: Literal["quarantine"] = "quarantine"
    reason: str = "quarantine by workflow"


class OrganizerProfileSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str | None = None
    root: str | None = None
    recursive: bool = DEFAULT_ORGANIZER_RECURSIVE
    image_extensions: list[str] = Field(default_factory=lambda: list(DEFAULT_ORGANIZER_IMAGE_EXTENSIONS))
    video_extensions: list[str] = Field(default_factory=lambda: list(DEFAULT_ORGANIZER_VIDEO_EXTENSIONS))
    rename_template: str = DEFAULT_ORGANIZER_RENAME_TEMPLATE
    statistics_template: str = DEFAULT_ORGANIZER_STATISTICS_TEMPLATE
    preserve_tags: list[str] = Field(default_factory=list)
    cleanup_patterns: list[str] = Field(default_factory=list)
    numbering_mode: Literal["none", "sequential"] = DEFAULT_ORGANIZER_NUMBERING_MODE
    numbering_start: int = DEFAULT_ORGANIZER_NUMBERING_START
    numbering_padding: int = DEFAULT_ORGANIZER_NUMBERING_PADDING
    mtime_mode: Literal["none", "ordered"] = DEFAULT_ORGANIZER_MTIME_MODE
    mtime_delay_seconds: float = DEFAULT_ORGANIZER_MTIME_DELAY_SECONDS

    @field_validator("name", mode="before")
    @classmethod
    def validate_name(cls, v: Any) -> str:
        return validate_profile_name(v)

    @field_validator("recursive", mode="before")
    @classmethod
    def validate_recursive_bool(cls, v: Any) -> bool:
        if isinstance(v, bool):
            return v
        raise ValueError("recursive must be a boolean")

    @field_validator("numbering_start", mode="before")
    @classmethod
    def validate_numbering_start(cls, v: Any) -> int:
        if isinstance(v, bool) or not isinstance(v, int):
            raise ValueError("numbering_start must be an integer")
        if v < 0:
            raise ValueError("numbering_start must be >= 0")
        return v

    @field_validator("numbering_padding", mode="before")
    @classmethod
    def validate_numbering_padding(cls, v: Any) -> int:
        if isinstance(v, bool) or not isinstance(v, int):
            raise ValueError("numbering_padding must be an integer")
        if v < 1 or v > 10:
            raise ValueError("numbering_padding must be between 1 and 10")
        return v

    @field_validator("mtime_delay_seconds", mode="before")
    @classmethod
    def validate_mtime_delay(cls, v: Any) -> float:
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ValueError("mtime_delay_seconds must be a finite number")
        val = float(v)
        if not math.isfinite(val):
            raise ValueError("mtime_delay_seconds must be a finite number")
        if val < 0.0 or val > 60.0:
            raise ValueError("mtime_delay_seconds must be between 0.0 and 60.0")
        return val

    @field_validator("image_extensions", mode="before")
    @classmethod
    def validate_images(cls, v: Any) -> list[str]:
        return validate_and_normalize_image_extensions(v)

    @field_validator("video_extensions", mode="before")
    @classmethod
    def validate_videos(cls, v: Any) -> list[str]:
        return validate_and_normalize_video_extensions(v)

    @field_validator("preserve_tags", mode="before")
    @classmethod
    def validate_tags(cls, v: Any) -> list[str]:
        return normalize_preserve_tags(v)

    @field_validator("cleanup_patterns", mode="before")
    @classmethod
    def validate_cleanup(cls, v: Any) -> list[str]:
        return validate_profile_cleanup_patterns(v)

    @field_validator("rename_template", mode="before")
    @classmethod
    def validate_rename_tmpl(cls, v: Any) -> str:
        return validate_rename_template(v)

    @field_validator("statistics_template", mode="before")
    @classmethod
    def validate_stats_tmpl(cls, v: Any) -> str:
        return validate_statistics_template(v)


class OrganizeStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    type: Literal["organize"] = "organize"
    profile_snapshot: OrganizerProfileSnapshot


class DedupeStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    type: Literal["dedupe"] = "dedupe"
    scorer_config: dict[str, Any] = Field(default_factory=dict)


WorkflowStep = Union[
    ScanStep,
    FilterStep,
    RenameStep,
    MoveStep,
    TouchStep,
    QuarantineStep,
    OrganizeStep,
    DedupeStep,
]


class WorkflowDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: int = 1
    mode: Literal["file", "organizer", "dedupe"]
    steps: list[WorkflowStep]

    @field_validator("steps", mode="before")
    @classmethod
    def pre_validate_raw_steps(cls, v: Any, info: ValidationInfo) -> Any:
        from app.workflows.validation import validate_raw_steps_types
        mode = info.data.get("mode") if info and hasattr(info, "data") else None
        if isinstance(v, list):
            validate_raw_steps_types(v, mode=mode)
        return v

    @field_validator("steps")
    @classmethod
    def validate_steps_not_empty(cls, v: list[WorkflowStep]) -> list[WorkflowStep]:
        from app.workflows.errors import WorkflowValidationError
        if not v:
            raise WorkflowValidationError("Workflow must contain at least one step", code="EMPTY_STEPS")
        return v


class RuntimeInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    root_ids: list[int] | None = None
    scan_job_id: int | None = None

    @field_validator("scan_job_id", mode="before")
    @classmethod
    def validate_scan_job_id(cls, v: Any) -> int | None:
        if v is None:
            return None
        if isinstance(v, bool) or not isinstance(v, int):
            raise ValueError("scan_job_id cannot be boolean; strict positive integer required")
        if v <= 0:
            raise ValueError("scan_job_id must be a positive integer")
        return v

    @field_validator("root_ids", mode="before")
    @classmethod
    def validate_root_ids(cls, v: Any) -> list[int] | None:
        if v is None:
            return None
        if not isinstance(v, list):
            raise ValueError("root_ids must be a list")
        for item in v:
            if isinstance(item, bool) or not isinstance(item, int) or item <= 0:
                raise ValueError("root_ids must contain positive integers, no booleans")
        return v


class WorkflowCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=1000)
    definition: WorkflowDefinition


class WorkflowUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=1000)
    expected_current_revision: int = Field(ge=1)
    definition: WorkflowDefinition | None = None


class WorkflowRollbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_revision: int = Field(ge=1)
    expected_current_revision: int = Field(ge=1)


class WorkflowListItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: int
    name: str
    description: str
    mode: Literal["file", "organizer", "dedupe"]
    current_revision: int
    is_builtin: bool
    archived_at: str | None = None
    created_at: str
    updated_at: str


class PlanRebuildPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=500)
    only_changed: bool = False


class PlanRebuildRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_compile_digest: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-fA-F]{64}$")
    plan_name: str | None = None


class WorkflowResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: int
    name: str
    description: str
    current_revision: int
    is_builtin: bool
    created_by_user_id: int | None = None
    archived_at: str | None = None
    created_at: str
    updated_at: str
    definition: WorkflowDefinition
    definition_sha256: str


class WorkflowRevisionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: int
    workflow_id: int
    revision: int
    definition: dict[str, Any]
    definition_sha256: str
    created_by_user_id: int | None = None
    created_at: str


class WorkflowPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int | None = Field(default=None, ge=1)
    runtime_inputs: RuntimeInputs | None = None
    root_ids: list[int] | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=500)
    only_changed: bool = False

    @model_validator(mode="after")
    def validate_root_contract(self) -> WorkflowPreviewRequest:
        from app.workflows.errors import WorkflowValidationError
        if self.root_ids is not None and self.runtime_inputs is not None:
            raise WorkflowValidationError(
                "Ambiguous root inputs: provide root_ids only within runtime_inputs",
                code="AMBIGUOUS_RUNTIME_INPUTS",
            )
        return self


class WorkflowPreviewItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_path: str
    target_path: str | None = None
    operation: str
    mtime_ns: int | None = None
    changed: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowPreviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workflow_id: int
    revision: int
    workflow_revision: int
    definition_sha256: str
    preview_source: Literal["index", "organizer-live-readonly", "completed-scan-readonly-safety"] = "index"
    live_filesystem_verified: Literal[False] = False
    compile_digest: str
    matched_count: int
    matched_bytes: int
    planned_operations_count: int
    page: int
    page_size: int
    total_pages: int
    items: list[WorkflowPreviewItem]


class WorkflowGeneratePlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_compile_digest: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-fA-F]{64}$")
    revision: int | None = Field(default=None, ge=1)
    runtime_inputs: RuntimeInputs | None = None
    root_ids: list[int] | None = None
    plan_name: str | None = None

    @model_validator(mode="after")
    def validate_root_contract(self) -> WorkflowGeneratePlanRequest:
        from app.workflows.errors import WorkflowValidationError
        if self.root_ids is not None and self.runtime_inputs is not None:
            raise WorkflowValidationError(
                "Ambiguous root inputs: provide root_ids only within runtime_inputs",
                code="AMBIGUOUS_RUNTIME_INPUTS",
            )
        return self


class WorkflowGeneratePlanResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_id: int
    plan_name: str
    status: str
    expected_changes: int
    compile_digest: str
