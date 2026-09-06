from __future__ import annotations

from typing import Any, Literal, Union
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.filters.schema import FilterNode


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

    name: str = Field(min_length=1)
    description: str | None = None
    root: str | None = None
    recursive: bool = True
    image_extensions: list[str] = Field(default_factory=list)
    video_extensions: list[str] = Field(default_factory=list)
    rename_template: str = "{name}"
    statistics_template: str | None = None
    preserve_tags: list[str] = Field(default_factory=list)
    cleanup_patterns: list[str] = Field(default_factory=list)
    numbering_mode: Literal["per_folder", "continuous", "none"] = "per_folder"
    numbering_start: int = 1
    numbering_padding: int = 4
    mtime_mode: Literal["preserve", "delay", "current", "none"] = "preserve"
    mtime_delay_seconds: float = 0.0

    @field_validator("numbering_start", "numbering_padding", mode="before")
    @classmethod
    def validate_strict_int(cls, v: Any) -> int:
        if isinstance(v, bool) or not isinstance(v, int):
            raise ValueError("Must be a valid integer")
        return v

    @field_validator("image_extensions", "video_extensions", "preserve_tags", "cleanup_patterns", mode="before")
    @classmethod
    def validate_string_list(cls, v: Any) -> list[str]:
        if isinstance(v, str) or not isinstance(v, list):
            raise ValueError("Must be a list of strings")
        for item in v:
            if not isinstance(item, str):
                raise ValueError("All elements must be strings")
        return v


class OrganizeStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    type: Literal["organize"] = "organize"
    profile_snapshot: OrganizerProfileSnapshot


WorkflowStep = Union[
    ScanStep,
    FilterStep,
    RenameStep,
    MoveStep,
    TouchStep,
    QuarantineStep,
    OrganizeStep,
]


class WorkflowDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: int = 1
    mode: Literal["file", "organizer"]
    steps: list[WorkflowStep]

    @field_validator("steps", mode="before")
    @classmethod
    def pre_validate_raw_steps(cls, v: Any) -> Any:
        from app.workflows.validation import validate_raw_steps_types
        if isinstance(v, list):
            validate_raw_steps_types(v)
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
    current_revision: int
    is_builtin: bool
    archived_at: str | None = None
    created_at: str
    updated_at: str


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
    preview_source: Literal["index", "organizer-live-readonly"] = "index"
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
