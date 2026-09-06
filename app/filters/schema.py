from __future__ import annotations

from typing import Any, Literal, Union
from pydantic import BaseModel, ConfigDict, Field


class LeafNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    operator: str
    value: Any
    case_sensitive: bool = False


class LogicalNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    op: Literal["and", "or", "not"]
    children: list[FilterNode] | None = None
    child: FilterNode | None = None


FilterNode = Union[LogicalNode, LeafNode]
LogicalNode.model_rebuild()


class FilterExpression(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node: FilterNode


class FilterPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    roots: list[str]
    filter: FilterNode | None = None
    page: int = 1
    page_size: int = 50
    sort_by: Literal["size", "mtime", "name", "path"] = "size"
    sort_order: Literal["asc", "desc"] = "desc"


class FilterPreviewItem(BaseModel):
    path: str
    relative_path: str
    name: str
    extension: str
    size: int
    mtime_ns: int
    media_type: str


class IndexRootMetadata(BaseModel):
    root: str
    last_indexed_at: str | None


class FilterPreviewResponse(BaseModel):
    preview_source: Literal["index"] = "index"
    live_filesystem_verified: Literal[False] = False
    matched_count: int
    matched_bytes: int
    page: int
    page_size: int
    total_pages: int
    roots: list[IndexRootMetadata]
    items: list[FilterPreviewItem]
