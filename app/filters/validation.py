from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.filters.media_types import MEDIA_TYPES, normalize_extension
from app.filters.schema import FilterNode, LeafNode, LogicalNode

MAX_DEPTH = 5
MAX_CHILDREN = 50
MAX_TOTAL_LEAVES = 200

ALLOWED_FIELDS = frozenset({"path", "name", "extension", "size", "mtime", "media_type"})

ALLOWED_OPERATORS_BY_FIELD = {
    "path": frozenset({"eq", "neq", "contains", "startswith", "endswith", "in", "nin"}),
    "name": frozenset({"eq", "neq", "contains", "startswith", "endswith", "in", "nin"}),
    "extension": frozenset({"eq", "neq", "in", "nin"}),
    "size": frozenset({"eq", "neq", "gt", "gte", "lt", "lte"}),
    "mtime": frozenset({"eq", "neq", "gt", "gte", "lt", "lte"}),
    "media_type": frozenset({"eq", "neq", "in", "nin"}),
}


class FilterValidationError(ValueError):
    """Raised when a filter expression fails validation."""
    pass


INT64_MAX = (1 << 63) - 1
MIN_MTIME_NS = 0
MAX_MTIME_NS = INT64_MAX
MAX_EPOCH_SECONDS = INT64_MAX // 1_000_000_000
EPOCH_UTC = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _parse_mtime_to_ns(val: Any) -> int:
    """Parse timezone-aware string ISO-8601 or int epoch seconds into UTC nanoseconds integer within SQLite INT64 range."""
    if isinstance(val, bool):
        raise FilterValidationError("mtime value cannot be a boolean")
    if isinstance(val, float):
        raise FilterValidationError("mtime value cannot be a float")
    if type(val) is int:
        if val < 0 or val > MAX_EPOCH_SECONDS:
            raise FilterValidationError(f"mtime epoch seconds out of supported range (0 to {MAX_EPOCH_SECONDS}), got {val}")
        ns = val * 1_000_000_000
        if ns < MIN_MTIME_NS or ns > MAX_MTIME_NS:
            raise FilterValidationError(f"mtime nanoseconds out of supported range ({MIN_MTIME_NS} to {MAX_MTIME_NS}), got {ns}")
        return ns
    if isinstance(val, str):
        val_str = val.strip()
        if val_str.endswith("Z") or val_str.endswith("z"):
            val_clean = val_str[:-1] + "+00:00"
        else:
            val_clean = val_str
        try:
            dt = datetime.fromisoformat(val_clean)
        except Exception as exc:
            raise FilterValidationError(f"Invalid mtime format '{val}': {exc}") from exc
        if dt.tzinfo is None:
            raise FilterValidationError("mtime ISO datetime must be timezone-aware (missing timezone)")
        dt_utc = dt.astimezone(timezone.utc)
        delta = dt_utc - EPOCH_UTC
        ns = delta.days * 86_400 * 1_000_000_000 + delta.seconds * 1_000_000_000 + delta.microseconds * 1_000
        if ns < MIN_MTIME_NS or ns > MAX_MTIME_NS:
            raise FilterValidationError(f"mtime nanoseconds out of supported range ({MIN_MTIME_NS} to {MAX_MTIME_NS}), got {ns}")
        return ns
    raise FilterValidationError(f"mtime value must be timezone-aware ISO string or integer epoch seconds, got {type(val).__name__}")



def validate_filter_ast(node: FilterNode, current_depth: int = 1, leaf_counter: list[int] | None = None) -> FilterNode:
    if leaf_counter is None:
        leaf_counter = [0]

    if current_depth > MAX_DEPTH:
        raise FilterValidationError(f"Filter AST exceeds maximum allowed depth of {MAX_DEPTH}")

    if isinstance(node, LeafNode):
        leaf_counter[0] += 1
        if leaf_counter[0] > MAX_TOTAL_LEAVES:
            raise FilterValidationError(f"Filter AST exceeds maximum total leaf nodes of {MAX_TOTAL_LEAVES}")

        field = node.field.strip().lower() if isinstance(node.field, str) else ""
        operator = node.operator.strip().lower() if isinstance(node.operator, str) else ""

        # Check deferred regex / matches
        if field == "regex" or operator == "matches":
            raise FilterValidationError("regex filtering is not supported in Gate5-A")

        if field not in ALLOWED_FIELDS:
            raise FilterValidationError(f"Unsupported field '{node.field}'. Allowed fields: {sorted(ALLOWED_FIELDS)}")

        allowed_ops = ALLOWED_OPERATORS_BY_FIELD[field]
        if operator not in allowed_ops:
            raise FilterValidationError(
                f"Unsupported operator '{node.operator}' for field '{field}'. Allowed operators: {sorted(allowed_ops)}"
            )

        val = node.value
        # Type & value validations
        if field == "size":
            if isinstance(val, bool) or type(val) is not int or val < 0:
                raise FilterValidationError("Size value must be an integer >= 0")
            clean_val = val
        elif field == "mtime":
            clean_val = _parse_mtime_to_ns(val)
        elif field == "extension":
            if operator in {"in", "nin"}:
                if type(val) is not list or len(val) == 0:
                    raise FilterValidationError(f"Value for extension {operator} must be a non-empty list of strings")
                clean_val = []
                for x in val:
                    if type(x) is not str or not x.strip():
                        raise FilterValidationError(f"All items for extension {operator} must be non-empty strings, got {x!r}")
                    clean_val.append(normalize_extension(x))
            else:
                if type(val) is not str or not val.strip():
                    raise FilterValidationError("Value for extension must be a non-empty string")
                clean_val = normalize_extension(val)
        elif field == "media_type":
            if operator in {"in", "nin"}:
                if type(val) is not list or len(val) == 0:
                    raise FilterValidationError(f"Value for media_type {operator} must be a non-empty list of strings")
                clean_val = []
                for x in val:
                    if type(x) is not str or not x.strip():
                        raise FilterValidationError(f"All items for media_type {operator} must be non-empty strings, got {x!r}")
                    mt = x.strip().lower()
                    if mt not in MEDIA_TYPES:
                        raise FilterValidationError(f"Invalid media_type '{x}'. Allowed: {sorted(MEDIA_TYPES)}")
                    clean_val.append(mt)
            else:
                if type(val) is not str or not val.strip():
                    raise FilterValidationError("Value for media_type must be a non-empty string")
                mt = val.strip().lower()
                if mt not in MEDIA_TYPES:
                    raise FilterValidationError(f"Invalid media_type '{val}'. Allowed: {sorted(MEDIA_TYPES)}")
                clean_val = mt
        elif field in {"path", "name"}:
            if operator in {"in", "nin"}:
                if type(val) is not list or len(val) == 0:
                    raise FilterValidationError(f"Value for {field} {operator} must be a non-empty list of strings")
                clean_val = []
                for x in val:
                    if type(x) is not str or not x.strip():
                        raise FilterValidationError(f"All items for {field} {operator} must be non-empty strings, got {x!r}")
                    clean_val.append(x)
            else:
                if type(val) is not str:
                    raise FilterValidationError(f"Value for {field} must be a string, got {type(val).__name__}")
                clean_val = val
        else:
            clean_val = val

        return LeafNode(
            field=field,
            operator=operator,
            value=clean_val,
            case_sensitive=bool(node.case_sensitive),
        )

    if isinstance(node, LogicalNode):
        op = node.op.strip().lower() if isinstance(node.op, str) else ""
        if op not in {"and", "or", "not"}:
            raise FilterValidationError(f"Unsupported logical operator '{node.op}'")

        if op in {"and", "or"}:
            if node.child is not None:
                raise FilterValidationError(f"Logical node '{op}' only allows 'children', got 'child'")
            children = node.children
            if not isinstance(children, list) or not children:
                raise FilterValidationError(f"Logical node '{op}' must have at least one child")
            if len(children) > MAX_CHILDREN:
                raise FilterValidationError(f"Logical node '{op}' exceeds maximum allowed children count of {MAX_CHILDREN}")
            validated_children = [
                validate_filter_ast(c, current_depth + 1, leaf_counter)
                for c in children
            ]
            return LogicalNode(op=op, children=validated_children)

        if op == "not":
            if node.children is not None:
                raise FilterValidationError("Logical node 'not' only allows 'child', got 'children'")
            child = node.child
            if child is None:
                raise FilterValidationError("Logical node 'not' only allows 'child', child is missing")
            validated_child = validate_filter_ast(child, current_depth + 1, leaf_counter)
            return LogicalNode(op="not", child=validated_child)

    raise FilterValidationError(f"Unknown filter node type: {type(node).__name__}")
