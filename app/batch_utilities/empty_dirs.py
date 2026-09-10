import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from app.batch_utilities.errors import (
    BatchUtilityScopeNotFoundError,
    BatchUtilityScopeOverlapError,
    BatchUtilitySymlinkBlockedError,
    BatchUtilityCrossRootError,
    BatchUtilityInvalidConfigError,
    BatchUtilityLimitExceededError,
)
from app.batch_utilities.flatten import FdPath


@dataclass(frozen=True)
class ScopeBinding:
    requested_path: str
    canonical_path: str
    device: int
    inode: int


@dataclass(frozen=True)
class DirectoryDecision:
    scope_root: str
    path: str
    relative_path: str
    depth: int
    device: int
    inode: int
    removable: bool
    reason_code: str | None = None


def is_path_allowed(path: Path, allowed_roots: Sequence[Path]) -> bool:
    try:
        resolved_p = path.resolve(strict=True)
    except OSError:
        return False

    for root in allowed_roots:
        try:
            resolved_r = root.resolve(strict=True)
            if resolved_p == resolved_r or resolved_r in resolved_p.parents:
                return True
        except OSError:
            continue
    return False


def is_reserved_quarantine_path(path: Path | str, quarantine_root: Path | str | None) -> bool:
    if not quarantine_root:
        return False
    try:
        p = Path(path).resolve()
        q = Path(quarantine_root).resolve()
        return p == q or q in p.parents
    except OSError:
        return False


def validate_remove_empty_scopes_preflight(
    scope_paths: Sequence[str],
    allowed_roots: Sequence[Path],
    quarantine_root: Path | None,
) -> tuple[ScopeBinding, ...]:
    if not scope_paths:
        raise BatchUtilityInvalidConfigError(
            "scope_paths must not be empty",
            details={"stage": "PREFLIGHT"},
        )

    bindings: list[ScopeBinding] = []
    canonical_paths: list[Path] = []

    for s_lex in scope_paths:
        raw = str(s_lex)
        raw_leaf = raw.rstrip("/") or "/"
        s_path = Path(raw)

        # 1. No-follow inspection on raw leaf
        try:
            st_leaf = os.lstat(raw_leaf)
        except FileNotFoundError:
            raise BatchUtilityScopeNotFoundError(
                f"Scope directory '{s_lex}' does not exist",
                details={"scope_path": s_lex, "stage": "PREFLIGHT"},
            )
        except OSError as e:
            raise BatchUtilityScopeNotFoundError(
                f"Failed to access scope '{s_lex}': {e}",
                details={"scope_path": s_lex, "error": str(e), "stage": "PREFLIGHT"},
            )

        if stat.S_ISLNK(st_leaf.st_mode):
            raise BatchUtilitySymlinkBlockedError(
                f"Scope path '{s_lex}' is a symlink",
                details={"scope_path": s_lex, "stage": "PREFLIGHT"},
            )

        if not stat.S_ISDIR(st_leaf.st_mode):
            raise BatchUtilityInvalidConfigError(
                f"Scope path '{s_lex}' is not a directory",
                details={"scope_path": s_lex, "stage": "PREFLIGHT"},
            )

        # 2. Strict physical resolution
        try:
            s_phys = s_path.resolve(strict=True)
        except FileNotFoundError:
            raise BatchUtilityScopeNotFoundError(
                f"Scope directory '{s_lex}' does not exist",
                details={"scope_path": s_lex, "stage": "PREFLIGHT"},
            )
        except OSError as e:
            raise BatchUtilityInvalidConfigError(
                f"Failed to resolve scope path '{s_lex}': {e}",
                details={"scope_path": s_lex, "errno": getattr(e, "errno", None), "stage": "PREFLIGHT"},
            )

        # Record physical identity - mandatory fail closed on error
        try:
            st_phys = os.stat(s_phys)
        except OSError as e:
            raise BatchUtilityInvalidConfigError(
                f"Failed to access scope '{s_lex}': {e}",
                details={"scope_path": s_lex, "errno": getattr(e, "errno", None), "stage": "PREFLIGHT"},
            )

        # 3. Quarantine and allowed root boundary checks
        if quarantine_root and is_reserved_quarantine_path(s_phys, quarantine_root):
            raise BatchUtilityCrossRootError(
                f"Scope '{s_lex}' is within reserved quarantine storage",
                details={"scope_path": s_lex, "stage": "PREFLIGHT"},
            )

        try:
            if not is_path_allowed(s_phys, allowed_roots):
                raise BatchUtilityCrossRootError(
                    f"Scope path '{s_lex}' is outside allowed roots",
                    details={"scope_path": s_lex, "stage": "PREFLIGHT"},
                )
        except BatchUtilityCrossRootError:
            raise
        except OSError as e:
            raise BatchUtilityInvalidConfigError(
                f"Failed to resolve scope path '{s_lex}': {e}",
                details={"scope_path": s_lex, "errno": getattr(e, "errno", None), "stage": "PREFLIGHT"},
            )

        # Note: Unlike E3 Flatten, E4 scope root may equal an allowed root!

        bindings.append(
            ScopeBinding(
                requested_path=s_lex,
                canonical_path=str(s_phys),
                device=st_phys.st_dev,
                inode=st_phys.st_ino,
            )
        )
        canonical_paths.append(s_phys)

    # 4. Check for physical duplicate / ancestor-descendant overlap
    # Physical duplicates
    if len(canonical_paths) != len(set(canonical_paths)):
        raise BatchUtilityScopeOverlapError(
            "Duplicate physical scope paths detected in action configuration",
            details={"scope_paths": list(scope_paths), "stage": "PREFLIGHT"},
        )

    # Ancestor-descendant overlap
    for i, p1 in enumerate(canonical_paths):
        for j, p2 in enumerate(canonical_paths):
            if i != j:
                if p1 in p2.parents:
                    raise BatchUtilityScopeOverlapError(
                        f"Scope path '{bindings[i].requested_path}' is an ancestor of '{bindings[j].requested_path}'",
                        details={
                            "scope_paths": [bindings[i].requested_path, bindings[j].requested_path],
                            "stage": "PREFLIGHT",
                        },
                    )

    return tuple(bindings)


def discover_remove_empty_dirs(
    bindings: Sequence[ScopeBinding],
    *,
    quarantine_root: Path | None = None,
    limit: int = 50000,
) -> tuple[DirectoryDecision, ...]:
    flags = os.O_RDONLY | os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW

    all_decisions: list[DirectoryDecision] = []
    total_examined = 0

    for binding in bindings:
        # 1. Open root directory with O_DIRECTORY | O_NOFOLLOW
        try:
            root_fd = os.open(binding.canonical_path, flags)
        except OSError as e:
            # Check if leaf symlink
            try:
                st = os.lstat(binding.canonical_path)
                if stat.S_ISLNK(st.st_mode):
                    raise BatchUtilitySymlinkBlockedError(
                        f"Scope path '{binding.canonical_path}' is a symlink",
                        details={"scope_path": binding.canonical_path, "stage": "DISCOVERY"},
                    )
            except OSError:
                pass
            raise BatchUtilityInvalidConfigError(
                f"Failed to access scope directory '{binding.canonical_path}': {e}",
                details={"scope_path": binding.canonical_path, "stage": "DISCOVERY"},
            )

        try:
            root_st = os.fstat(root_fd)
            if not stat.S_ISDIR(root_st.st_mode):
                raise BatchUtilityInvalidConfigError(
                    f"Scope path '{binding.canonical_path}' is not a directory",
                    details={"scope_path": binding.canonical_path, "stage": "DISCOVERY"},
                )
            if (root_st.st_dev, root_st.st_ino) != (binding.device, binding.inode):
                raise BatchUtilityInvalidConfigError(
                    f"SCOPE_IDENTITY_CHANGED: Scope '{binding.canonical_path}' physical identity changed",
                    details={
                        "scope_path": binding.canonical_path,
                        "error": "SCOPE_IDENTITY_CHANGED",
                        "stage": "DISCOVERY",
                        "expected_device": binding.device,
                        "current_device": root_st.st_dev,
                        "expected_inode": binding.inode,
                        "current_inode": root_st.st_ino,
                    },
                )

            # Recursive post-order traversal using dir_fd
            def _traverse(
                dir_fd: int,
                dir_path: str,
                rel_path: str,
                depth: int,
                expected_dev: int,
                expected_ino: int,
            ) -> tuple[bool, list[DirectoryDecision]]:
                nonlocal total_examined
                contains_blocker = False
                dir_decisions: list[DirectoryDecision] = []

                # Enumerate children
                try:
                    dir_handle = FdPath(dir_fd, dir_path)
                    with os.scandir(dir_handle) as it:
                        entries = list(it)
                except OSError as e:
                    raise BatchUtilityInvalidConfigError(
                        f"Failed to scan directory '{dir_path}': {e}",
                        details={"dir_path": dir_path, "errno": getattr(e, "errno", None), "stage": "DISCOVERY"},
                    )

                for entry in entries:
                    child_path = os.path.join(dir_path, entry.name)
                    child_rel = f"{rel_path}/{entry.name}" if rel_path else entry.name

                    # Reserved quarantine check
                    if quarantine_root and is_reserved_quarantine_path(child_path, quarantine_root):
                        contains_blocker = True
                        continue

                    try:
                        st = entry.stat(follow_symlinks=False)
                    except OSError as e:
                        raise BatchUtilityInvalidConfigError(
                            f"Failed to stat directory child '{child_path}': {e}",
                            details={"child_path": child_path, "errno": getattr(e, "errno", None), "stage": "DISCOVERY"},
                        )

                    # Symlinks are never followed and make directory non-empty
                    if stat.S_ISLNK(st.st_mode):
                        contains_blocker = True
                        continue

                    # Files and special objects make directory non-empty
                    if not stat.S_ISDIR(st.st_mode):
                        contains_blocker = True
                        continue

                    # Real directory child: open relative to parent dir_fd
                    total_examined += 1
                    if total_examined > limit:
                        raise BatchUtilityLimitExceededError(
                            "Remove empty directories utility supports maximum 50,000 candidates",
                            details={"limit": limit, "stage": "DISCOVERY"},
                        )

                    try:
                        child_fd = os.open(entry.name, flags, dir_fd=dir_fd)
                    except OSError as e:
                        # If open failed because of symlink swap
                        try:
                            st_recheck = os.lstat(child_path)
                            if stat.S_ISLNK(st_recheck.st_mode):
                                raise BatchUtilitySymlinkBlockedError(
                                    f"Directory child '{child_path}' is a symlink",
                                    details={"child_path": child_path, "stage": "DISCOVERY"},
                                )
                        except (BatchUtilitySymlinkBlockedError, BatchUtilityInvalidConfigError):
                            raise
                        except OSError:
                            pass
                        raise BatchUtilityInvalidConfigError(
                            f"Failed to open directory child '{child_path}': {e}",
                            details={"child_path": child_path, "errno": getattr(e, "errno", None), "stage": "DISCOVERY"},
                        )

                    try:
                        child_st = os.fstat(child_fd)
                        if stat.S_ISLNK(child_st.st_mode):
                            raise BatchUtilitySymlinkBlockedError(
                                f"Directory child '{child_path}' is a symlink",
                                details={"child_path": child_path, "stage": "DISCOVERY"},
                            )
                        if not stat.S_ISDIR(child_st.st_mode):
                            raise BatchUtilityInvalidConfigError(
                                f"Directory child '{child_path}' is not a directory",
                                details={"child_path": child_path, "stage": "DISCOVERY"},
                            )
                        if (child_st.st_dev, child_st.st_ino) != (st.st_dev, st.st_ino):
                            raise BatchUtilityInvalidConfigError(
                                f"Child directory '{child_path}' physical identity changed during acquisition",
                                details={
                                    "child_path": child_path,
                                    "error": "CHILD_IDENTITY_CHANGED",
                                    "stage": "DISCOVERY",
                                },
                            )

                        child_empty, sub_decs = _traverse(
                            dir_fd=child_fd,
                            dir_path=child_path,
                            rel_path=child_rel,
                            depth=depth + 1,
                            expected_dev=child_st.st_dev,
                            expected_ino=child_st.st_ino,
                        )
                        dir_decisions.extend(sub_decs)
                        if not child_empty:
                            contains_blocker = True
                    finally:
                        os.close(child_fd)

                is_empty = (not contains_blocker)
                if depth > 0:
                    dir_decisions.append(
                        DirectoryDecision(
                            scope_root=binding.canonical_path,
                            path=dir_path,
                            relative_path=rel_path,
                            depth=depth,
                            device=expected_dev,
                            inode=expected_ino,
                            removable=is_empty,
                            reason_code=None if is_empty else "NON_EMPTY",
                        )
                    )

                return is_empty, dir_decisions

            _, scope_decisions = _traverse(
                dir_fd=root_fd,
                dir_path=binding.canonical_path,
                rel_path="",
                depth=0,
                expected_dev=binding.device,
                expected_ino=binding.inode,
            )
            all_decisions.extend(scope_decisions)

        finally:
            os.close(root_fd)

    # Sort decisions deterministically:
    # Deepest-first, then alphabetical relative_path
    sorted_decisions = sorted(
        all_decisions,
        key=lambda d: (-d.depth, d.relative_path),
    )

    return tuple(sorted_decisions)
