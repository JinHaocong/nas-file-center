from __future__ import annotations

from typing import Iterable
from sqlalchemy import ColumnElement, and_, func, not_, or_

from app.models import IndexedPath

DEFAULT_EXCLUDE_DIR_NAMES: list[str] = [
    ".git",
    ".recycle",
    "@eaDir",
    ".nas-file-center-trash",
]

MAX_EXCLUDE_RULES = 64
MAX_RULE_LENGTH = 128


def validate_exclude_rules(rules: Iterable[str]) -> list[str]:
    """
    Validate and normalize global exclude rules.
    Rules must be directory basenames (no / or \\, not empty, not . or ..).
    Returns deduplicated list maintaining order.
    """
    if not isinstance(rules, (list, tuple, set)):
        raise ValueError("Exclude rules must be a list of directory names")

    seen = set()
    result: list[str] = []

    for item in rules:
        if not isinstance(item, str):
            raise ValueError("Each exclude rule must be a string")
        if item != item.strip():
            raise ValueError(f"Exclude rule '{item}' cannot contain leading or trailing whitespace")
        if not item or item in {".", ".."}:
            raise ValueError(f"Exclude rule '{item}' cannot be empty or dot references")
        if "/" in item or "\\" in item:
            raise ValueError(f"Exclude rule '{item}' cannot contain path separators")
        if "\0" in item:
            raise ValueError("Exclude rule cannot contain NUL characters")
        if len(item) > MAX_RULE_LENGTH:
            raise ValueError(f"Exclude rule '{item}' exceeds maximum length of {MAX_RULE_LENGTH}")

        if item not in seen:
            seen.add(item)
            result.append(item)

    if len(result) > MAX_EXCLUDE_RULES:
        raise ValueError(f"Maximum allowed exclude rules is {MAX_EXCLUDE_RULES}, got {len(result)}")

    return result


def _escape_like(val: str) -> str:
    return val.replace("!", "!!").replace("%", "!%").replace("_", "!_")


def build_exclude_predicates(
    exclude_dir_names: Iterable[str],
    quarantine_root: str | None = None,
) -> ColumnElement[bool]:
    """
    Build SQL predicates to exclude matching directory segments and quarantine root.
    Segment-aware: matches 'dir/', '%/dir/%', '%/dir', or 'dir'.
    """
    clauses: list[ColumnElement[bool]] = []
    path_col = IndexedPath.relative_path

    for d in exclude_dir_names:
        esc = _escape_like(d.lower())
        # Matches:
        # 1. Exact match: relative_path == d
        # 2. Leading segment: relative_path LIKE 'd/%'
        # 3. Middle segment: relative_path LIKE '%/d/%'
        # 4. Trailing segment: relative_path LIKE '%/d'
        clauses.append(
            or_(
                func.lower(path_col) == d.lower(),
                func.lower(path_col).like(f"{esc}/%", escape="!"),
                func.lower(path_col).like(f"%/{esc}/%", escape="!"),
                func.lower(path_col).like(f"%/{esc}", escape="!"),
            )
        )

    # Hard exclude for quarantine_root if configured
    if quarantine_root:
        q_clean = quarantine_root.strip()
        if q_clean:
            q_esc = _escape_like(q_clean.lower())
            clauses.append(
                or_(
                    func.lower(IndexedPath.absolute_path) == q_clean.lower(),
                    func.lower(IndexedPath.absolute_path).like(f"{q_esc}/%", escape="!"),
                )
            )

    if not clauses:
        return and_()

    return not_(or_(*clauses))
