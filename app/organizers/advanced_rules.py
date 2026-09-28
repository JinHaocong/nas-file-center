from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DirectoryDepthRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    rename_from_depth: int = Field(default=2, ge=2, le=64)


class FileNumberingRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    start: int = Field(default=1, ge=0)
    padding: int = Field(default=3, ge=1, le=10)
    sort: Literal["natural_name"] = "natural_name"
    extension_mode: Literal["preserve"] = "preserve"


class LatestChildPrefixRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    prefix: str = Field(default="New ", min_length=1, max_length=64)
    timestamp: Literal["mtime_ns"] = "mtime_ns"

    @field_validator("prefix")
    @classmethod
    def validate_prefix(cls, value: str) -> str:
        if "/" in value or "\x00" in value:
            raise ValueError("latest_child_prefix.prefix must not contain '/' or NUL")
        if value.strip() == "":
            raise ValueError("latest_child_prefix.prefix must not be blank")
        return value


class SingleChildWrapperCollapseRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    wrapper_depth: Literal[2] = 2
    child_type: Literal["directory"] = "directory"


class OrganizerAdvancedRules(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    directory_depth: DirectoryDepthRule = Field(default_factory=DirectoryDepthRule)
    file_numbering: FileNumberingRule = Field(default_factory=FileNumberingRule)
    latest_child_prefix: LatestChildPrefixRule = Field(default_factory=LatestChildPrefixRule)
    single_child_wrapper_collapse: SingleChildWrapperCollapseRule = Field(
        default_factory=SingleChildWrapperCollapseRule
    )


def advanced_rules_enabled(value: dict[str, Any] | OrganizerAdvancedRules | None) -> bool:
    if value is None:
        return False
    model = value if isinstance(value, OrganizerAdvancedRules) else OrganizerAdvancedRules.model_validate(value)
    return any(
        (
            model.directory_depth.enabled,
            model.file_numbering.enabled,
            model.latest_child_prefix.enabled,
            model.single_child_wrapper_collapse.enabled,
        )
    )


def normalize_advanced_rules(
    value: Any,
    *,
    recursive: bool,
    mtime_mode: str,
) -> dict[str, Any]:
    if value is None or value == {}:
        return {}

    model = value if isinstance(value, OrganizerAdvancedRules) else OrganizerAdvancedRules.model_validate(value)

    if advanced_rules_enabled(model) and recursive is not True:
        raise ValueError("启用 Organizer Advanced Rules 时 recursive 必须为 true")

    if model.latest_child_prefix.enabled and mtime_mode == "ordered":
        raise ValueError("latest_child_prefix 与 ordered mtime 模式不能同时启用")

    return model.model_dump()
