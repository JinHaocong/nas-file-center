from __future__ import annotations

from typing import Any
from sqlalchemy import ColumnElement, and_, func, not_, or_

from app.models import IndexedPath
from app.filters.media_types import (
    ARCHIVE_EXTENSIONS,
    AUDIO_EXTENSIONS,
    DOCUMENT_EXTENSIONS,
    IMAGE_EXTENSIONS,
    VIDEO_EXTENSIONS,
    get_extensions_for_media_type,
)
from app.filters.schema import FilterNode, LeafNode, LogicalNode

ALL_KNOWN_EXTENSIONS: frozenset[str] = (
    IMAGE_EXTENSIONS | VIDEO_EXTENSIONS | AUDIO_EXTENSIONS | DOCUMENT_EXTENSIONS | ARCHIVE_EXTENSIONS
)


def _escape_like(val: str) -> str:
    """Escape LIKE wildcard characters %, _, and ! with exclamation as escape char."""
    return val.replace("!", "!!").replace("%", "!%").replace("_", "!_")


def _compile_media_type_single(media_type: str) -> ColumnElement[bool]:
    mt = media_type.strip().lower()
    suffix_lower = func.lower(IndexedPath.suffix)
    if mt == "other":
        targets = [f".{x}" for x in ALL_KNOWN_EXTENSIONS] + list(ALL_KNOWN_EXTENSIONS)
        return suffix_lower.not_in(targets)
    
    exts = get_extensions_for_media_type(mt)
    targets = [f".{x}" for x in exts] + list(exts)
    return suffix_lower.in_(targets)


def compile_filter_to_sql(node: FilterNode) -> ColumnElement[bool]:
    """
    Compile a validated Filter AST into a SQLAlchemy ColumnElement predicate on IndexedPath.
    """
    if isinstance(node, LogicalNode):
        if node.op == "and":
            return and_(*(compile_filter_to_sql(c) for c in (node.children or [])))
        if node.op == "or":
            return or_(*(compile_filter_to_sql(c) for c in (node.children or [])))
        if node.op == "not":
            if node.child is not None:
                return not_(compile_filter_to_sql(node.child))
            if node.children and len(node.children) == 1:
                return not_(compile_filter_to_sql(node.children[0]))
            raise ValueError("LogicalNode 'not' requires a child")
        raise ValueError(f"Unknown logical op: {node.op}")

    if isinstance(node, LeafNode):
        field = node.field
        op = node.operator
        val = node.value
        cs = node.case_sensitive

        if field == "size":
            col = IndexedPath.size
            if op == "eq": return col == val
            if op == "neq": return col != val
            if op == "gt": return col > val
            if op == "gte": return col >= val
            if op == "lt": return col < val
            if op == "lte": return col <= val

        elif field == "mtime":
            col = IndexedPath.mtime_ns
            if op == "eq": return col == val
            if op == "neq": return col != val
            if op == "gt": return col > val
            if op == "gte": return col >= val
            if op == "lt": return col < val
            if op == "lte": return col <= val

        elif field == "extension":
            suffix_lower = func.lower(IndexedPath.suffix)
            if op == "eq":
                ext = str(val).lower()
                return suffix_lower.in_([f".{ext}", ext])
            if op == "neq":
                ext = str(val).lower()
                return suffix_lower.not_in([f".{ext}", ext])
            if op == "in":
                exts = [str(x).lower() for x in val]
                targets = [f".{x}" for x in exts] + exts
                return suffix_lower.in_(targets)
            if op == "nin":
                exts = [str(x).lower() for x in val]
                targets = [f".{x}" for x in exts] + exts
                return suffix_lower.not_in(targets)

        elif field == "media_type":
            if op == "eq":
                return _compile_media_type_single(str(val))
            if op == "neq":
                return not_(_compile_media_type_single(str(val)))
            if op == "in":
                return or_*([_compile_media_type_single(str(x)) for x in val])
            if op == "nin":
                return and_*([not_(_compile_media_type_single(str(x))) for x in val])

        elif field in {"path", "name"}:
            col = IndexedPath.relative_path if field == "path" else IndexedPath.basename
            if op == "eq":
                return col == val if cs else func.lower(col) == val.lower()
            if op == "neq":
                return col != val if cs else func.lower(col) != val.lower()
            if op == "contains":
                if cs:
                    return func.instr(col, val) > 0
                return func.lower(col).like(f"%{_escape_like(val.lower())}%", escape="!")
            if op == "startswith":
                if cs:
                    return func.substr(col, 1, len(val)) == val
                return func.lower(col).like(f"{_escape_like(val.lower())}%", escape="!")
            if op == "endswith":
                if cs:
                    return func.substr(col, -len(val)) == val
                return func.lower(col).like(f"%{_escape_like(val.lower())}", escape="!")
            if op == "in":
                vals = [str(x) for x in val]
                return col.in_(vals) if cs else func.lower(col).in_([x.lower() for x in vals])
            if op == "nin":
                vals = [str(x) for x in val]
                return col.not_in(vals) if cs else func.lower(col).not_in([x.lower() for x in vals])

        raise ValueError(f"Unhandled field/operator combination: {field} {op}")

    raise ValueError(f"Unknown FilterNode type: {type(node).__name__}")
