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


def _parse_mtime_to_ns(val: Any) -> int:
    """Parse string ISO-8601 or int seconds/ns into UTC nanoseconds integer."""
    if isinstance(val, bool):
        raise FilterValidationError("mtime value cannot be a boolean")
    if isinstance(val, (int, float)):
        int_val = int(val)
        # If timestamp looks like seconds (< 1e11), convert to ns
        if int_val < 100_000_000_000:
            return int_val * 1_000_000_000
        return int_val
    if isinstance(val, str):
        val_str = val.strip()
        try:
            # Handle trailing Z for UTC
            if val_str.endswith("Z") or val_str.endswith("z"):
                val_clean = val_str[:-1] + "+00:00"
            else:
                val_clean = val_str
            dt = datetime.fromisoformat(val_clean)
            if dt.tzinfo is None:
                # Force UTC if timezone naive
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp() * 1_000_000_000)
        except Exception as exc:
            raise FilterValidationError(f"Invalid mtime format '{val}': {exc}") from exc
    raise FilterValidationError(f"mtime value must be ISO-8601 string or integer timestamp, got {type(val).__name__}")


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
            if isinstance(val, bool) or not isinstance(val, int) or val < 0:
                raise FilterValidationError("Size value must be an integer >= 0")
            clean_val = val
        elif field == "mtime":
            clean_val = _parse_mtime_to_ns(val)
        elif field == "extension":
            if operator in {"in", "nin"}:
                if not isinstance(val, (list, tuple, set)) or not val:
                    raise FilterValidationError(f"Value for extension {operator} must be a non-empty list of strings")
                clean_val = [normalize_extension(str(x)) for x in val]
            else:
                if not isinstance(val, str) or not val.strip():
                    raise FilterValidationError("Value for extension must be a non-empty string")
                clean_val = normalize_extension(val)
        elif field == "media_type":
            if operator in {"in", "nin"}:
                if not isinstance(val, (list, tuple, set)) or not val:
                    raise FilterValidationError(f"Value for media_type {operator} must be a non-empty list")
                clean_val = []
                for x in val:
                    mt = str(x).strip().lower()
                    if mt not in MEDIA_TYPES:
                        raise FilterValidationError(f"Invalid media_type '{x}'. Allowed: {sorted(MEDIA_TYPES)}")
                    clean_val.append(mt)
            else:
                mt = str(val).strip().lower()
                if mt not in MEDIA_TYPES:
                    raise FilterValidationError(f"Invalid media_type '{val}'. Allowed: {sorted(MEDIA_TYPES)}")
                clean_val = mt
        elif field in {"path", "name"}:
            if operator in {"in", "nin"}:
                if not isinstance(val, (list, tuple, set)) or not val:
                    raise FilterValidationError(f"Value for {field} {operator} must be a non-empty list of strings")
                clean_val = [str(x) for x in val]
            else:
                if not isinstance(val, str):
                    raise FilterValidationError(f"Value for {field} must be a string")
                clean_val = str(val)
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
            children = node.children or []
            if not children:
                raise FilterValidationError(f"Logical node '{op}' must have at least one child")
            if len(children) > MAX_CHILDREN:
                raise FilterValidationError(f"Logical node '{op}' exceeds maximum allowed children count of {MAX_CHILDREN}")
            validated_children = [
                validate_filter_ast(c, current_depth + 1, leaf_counter)
                for c in children
            ]
            return LogicalNode(op=op, children=validated_children)

        if op == "not":
            child = node.child
            if child is None:
                if node.children and len(node.children) == 1:
                    child = node.children[0]
                else:
                    raise FilterValidationError("Logical node 'not' must have exactly one child")
            elif node.children and len(node.children) > 0:
                raise FilterValidationError("Logical node 'not' cannot specify both 'child' and 'children'")
            validated_child = validate_filter_ast(child, current_depth + 1, leaf_counter)
            return LogicalNode(op="not", child=validated_child)

    raise FilterValidationError(f"Unknown filter node type: {type(node).__name__}")
