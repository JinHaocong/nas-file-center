from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import stat
from typing import Any

from app.planning.dedupe_preview import (
    _directory_binding_matches,
    _open_absolute_directory_nofollow,
    _recursive_directory_open_flags,
    _relative_reserved_quarantine_path,
    _snapshot_real_regular_files_recursive,
)


@dataclass(frozen=True)
class RecursiveProtectionSnapshot:
    """Public sampled snapshot contract for Recursive Last-File Protection.

    Architecture Amendment A intentionally does not treat the finite descriptor-
    bound verification passes underneath this API as an atomic snapshot against
    arbitrary external writers. They are defense in depth; callers must still
    perform the frozen Validate/Execute live protection checks.
    """

    count: int
    stable: bool
    device: int | None
    inode: int | None
    tree_identity_digest: str | None

    def digest_payload(self) -> dict[str, Any]:
        return {
            "stable": self.stable,
            "device": self.device,
            "inode": self.inode,
            "tree_identity_digest": self.tree_identity_digest,
        }


def snapshot_recursive_regular_files(
    directory: str | Path,
    *,
    quarantine_root: str | Path | None = None,
) -> RecursiveProtectionSnapshot:
    """Read one descriptor-bound, no-follow sampled recursive file snapshot."""

    snapshot = _snapshot_real_regular_files_recursive(
        directory,
        quarantine_root=quarantine_root,
    )
    return RecursiveProtectionSnapshot(
        count=snapshot.count,
        stable=snapshot.stable,
        device=snapshot.device,
        inode=snapshot.inode,
        tree_identity_digest=snapshot.tree_identity_digest,
    )


@dataclass(frozen=True)
class RecursiveProtectionLiveCount:
    """Execute-time exact recursive count without Preview tree-digest materialization.

    This reader keeps Amendment A's descriptor-bound/no-follow and fail-closed
    semantics, but it intentionally does not build deterministic identity rows or
    rebind every row because Execute only needs the current regular-file count and
    protected-directory identity. It performs two fresh descriptor-bound count
    passes and a final protected-root rebind. External writers still cannot be
    atomically excluded from the final syscall gap, as documented by Amendment A.
    """

    count: int
    stable: bool
    device: int | None
    inode: int | None


def _unstable_live_count(
    *,
    device: int | None = None,
    inode: int | None = None,
) -> RecursiveProtectionLiveCount:
    return RecursiveProtectionLiveCount(
        count=0,
        stable=False,
        device=device,
        inode=inode,
    )


def _count_live_regular_files_chain_pass(
    root_fd: int,
    *,
    protected_relative_dirs: tuple[str, ...],
    excluded_relative_path: str | None,
) -> tuple[int, ...] | None:
    """Consume root_fd and return exact counts for one nested ancestor chain."""

    dir_flags = _recursive_directory_open_flags()
    if dir_flags is None:
        try:
            os.close(root_fd)
        except OSError:
            pass
        return None

    regular_flags = os.O_RDONLY | os.O_NOFOLLOW
    counts = [0 for _ in protected_relative_dirs]
    stable = True
    stack: list[tuple[int, str]] = [(root_fd, ".")]

    while stack and stable:
        current_fd, relative_dir = stack.pop()
        try:
            try:
                iterator = os.scandir(current_fd)
            except OSError:
                stable = False
                continue

            try:
                for entry in iterator:
                    relative_path = (
                        entry.name
                        if relative_dir == "."
                        else f"{relative_dir}/{entry.name}"
                    )
                    if (
                        excluded_relative_path is not None
                        and relative_path == excluded_relative_path
                    ):
                        continue

                    try:
                        entry_st = entry.stat(follow_symlinks=False)
                    except OSError:
                        stable = False
                        break

                    if stat.S_ISLNK(entry_st.st_mode):
                        continue

                    if stat.S_ISREG(entry_st.st_mode):
                        try:
                            file_fd = os.open(
                                entry.name,
                                regular_flags,
                                dir_fd=current_fd,
                            )
                        except OSError:
                            stable = False
                            break
                        try:
                            opened_file_st = os.fstat(file_fd)
                        finally:
                            os.close(file_fd)
                        if (
                            not stat.S_ISREG(opened_file_st.st_mode)
                            or int(opened_file_st.st_dev) != int(entry_st.st_dev)
                            or int(opened_file_st.st_ino) != int(entry_st.st_ino)
                        ):
                            stable = False
                            break

                        for index, protected_relative in enumerate(protected_relative_dirs):
                            if (
                                protected_relative == "."
                                or relative_path.startswith(protected_relative + "/")
                            ):
                                counts[index] += 1
                        continue

                    if stat.S_ISDIR(entry_st.st_mode):
                        try:
                            child_fd = os.open(
                                entry.name,
                                dir_flags,
                                dir_fd=current_fd,
                            )
                        except OSError:
                            stable = False
                            break
                        child_st = os.fstat(child_fd)
                        if (
                            not stat.S_ISDIR(child_st.st_mode)
                            or int(child_st.st_dev) != int(entry_st.st_dev)
                            or int(child_st.st_ino) != int(entry_st.st_ino)
                        ):
                            os.close(child_fd)
                            stable = False
                            break
                        stack.append((child_fd, relative_path))
            finally:
                iterator.close()
        finally:
            try:
                os.close(current_fd)
            except OSError:
                pass

    if not stable:
        for fd, _relative_dir in stack:
            try:
                os.close(fd)
            except OSError:
                pass
        return None

    return tuple(counts)


def _count_live_regular_files_pass(
    root_fd: int,
    *,
    excluded_relative_path: str | None,
) -> int | None:
    """Consume root_fd and return one exact descriptor-bound regular-file count."""

    counts = _count_live_regular_files_chain_pass(
        root_fd,
        protected_relative_dirs=(".",),
        excluded_relative_path=excluded_relative_path,
    )
    return counts[0] if counts is not None else None

def live_count_recursive_regular_files(
    directory: str | Path,
    *,
    quarantine_root: str | Path | None = None,
) -> RecursiveProtectionLiveCount:
    """Return a trustworthy current exact count for Execute Last-File preflight.

    Preview/Freeze/Validate continue to use the stronger sampled snapshot reader
    with deterministic tree identity. Execute does not consume that digest; doing
    its O(number-of-tree-rows * depth) final row rebind for every Quarantine item
    is therefore redundant work. Two independently reacquired descriptor-bound
    count passes plus a final protected-root binding check preserve the Execute
    authority actually required by Amendment A.
    """

    excluded_relative_path = _relative_reserved_quarantine_path(
        directory,
        quarantine_root,
    )
    if excluded_relative_path == ".":
        return _unstable_live_count()

    first_opened = _open_absolute_directory_nofollow(directory)
    if first_opened is None:
        return _unstable_live_count()
    first_fd, first_st = first_opened
    root_device = int(first_st.st_dev)
    root_inode = int(first_st.st_ino)

    first_count = _count_live_regular_files_pass(
        first_fd,
        excluded_relative_path=excluded_relative_path,
    )
    if first_count is None:
        return _unstable_live_count(device=root_device, inode=root_inode)

    second_opened = _open_absolute_directory_nofollow(directory)
    if second_opened is None:
        return _unstable_live_count(device=root_device, inode=root_inode)
    second_fd, second_st = second_opened
    if (
        int(second_st.st_dev) != root_device
        or int(second_st.st_ino) != root_inode
    ):
        os.close(second_fd)
        return _unstable_live_count(device=root_device, inode=root_inode)

    second_count = _count_live_regular_files_pass(
        second_fd,
        excluded_relative_path=excluded_relative_path,
    )
    if second_count is None or second_count != first_count:
        return _unstable_live_count(device=root_device, inode=root_inode)

    if not _directory_binding_matches(directory, root_device, root_inode):
        return _unstable_live_count(device=root_device, inode=root_inode)

    return RecursiveProtectionLiveCount(
        count=second_count,
        stable=True,
        device=root_device,
        inode=root_inode,
    )


@dataclass(frozen=True)
class RecursiveProtectionBindingChain:
    """Stable lexical bindings for a nested protected-ancestor chain."""

    stable: bool
    failure_path: str | None
    bindings: tuple[tuple[str, int, int], ...]


def capture_recursive_directory_binding_chain(
    directories: tuple[str | Path, ...] | list[str | Path],
) -> RecursiveProtectionBindingChain:
    """Capture lightweight no-follow directory bindings after a trusted NFC mutation.

    Unlike the live recursive count reader this does not traverse file payloads.
    It reopens every exact protected directory twice and performs a final lexical
    rebind. This is intended only for rolling Execute authority after a completed
    mutation in the same serialized Worker plan.
    """

    if not directories:
        return RecursiveProtectionBindingChain(
            stable=False,
            failure_path=None,
            bindings=(),
        )

    raw_paths = tuple(str(path) for path in directories)
    normalized_paths = tuple(os.path.normpath(path) for path in raw_paths)
    for raw, normalized in zip(raw_paths, normalized_paths):
        if not os.path.isabs(raw) or raw != normalized:
            return RecursiveProtectionBindingChain(
                stable=False,
                failure_path=raw,
                bindings=(),
            )

    if len(set(normalized_paths)) != len(normalized_paths):
        return RecursiveProtectionBindingChain(
            stable=False,
            failure_path=normalized_paths[0],
            bindings=(),
        )

    scan_root = normalized_paths[-1]
    for index, path in enumerate(normalized_paths):
        try:
            if os.path.commonpath([path, scan_root]) != scan_root:
                return RecursiveProtectionBindingChain(
                    stable=False,
                    failure_path=path,
                    bindings=(),
                )
            if index + 1 < len(normalized_paths):
                parent = normalized_paths[index + 1]
                if os.path.commonpath([path, parent]) != parent:
                    return RecursiveProtectionBindingChain(
                        stable=False,
                        failure_path=path,
                        bindings=(),
                    )
        except ValueError:
            return RecursiveProtectionBindingChain(
                stable=False,
                failure_path=path,
                bindings=(),
            )

    def collect() -> tuple[tuple[str, int, int], ...] | None:
        rows: list[tuple[str, int, int]] = []
        for path in normalized_paths:
            opened = _open_absolute_directory_nofollow(path)
            if opened is None:
                return None
            fd, st = opened
            try:
                if not stat.S_ISDIR(st.st_mode):
                    return None
                rows.append((path, int(st.st_dev), int(st.st_ino)))
            finally:
                os.close(fd)
        return tuple(rows)

    first = collect()
    if first is None:
        return RecursiveProtectionBindingChain(
            stable=False,
            failure_path=scan_root,
            bindings=(),
        )
    second = collect()
    if second is None:
        return RecursiveProtectionBindingChain(
            stable=False,
            failure_path=scan_root,
            bindings=first,
        )
    if first != second:
        mismatch = next(
            (
                first_row[0]
                for first_row, second_row in zip(first, second)
                if first_row != second_row
            ),
            scan_root,
        )
        return RecursiveProtectionBindingChain(
            stable=False,
            failure_path=mismatch,
            bindings=second,
        )

    for path, device, inode in second:
        if not _directory_binding_matches(path, device, inode):
            return RecursiveProtectionBindingChain(
                stable=False,
                failure_path=path,
                bindings=second,
            )

    return RecursiveProtectionBindingChain(
        stable=True,
        failure_path=None,
        bindings=second,
    )


@dataclass(frozen=True)
class RecursiveProtectionLiveChain:
    """One Execute-time sampled count for an exact nested protected-ancestor chain."""

    stable: bool
    failure_path: str | None
    samples: tuple[tuple[str, RecursiveProtectionLiveCount], ...]


def _unstable_live_chain(
    paths: tuple[str, ...],
    *,
    failure_path: str,
    identities: dict[str, tuple[int, int]] | None = None,
) -> RecursiveProtectionLiveChain:
    identities = identities or {}
    samples = tuple(
        (
            path,
            _unstable_live_count(
                device=(identities.get(path) or (None, None))[0],
                inode=(identities.get(path) or (None, None))[1],
            ),
        )
        for path in paths
    )
    return RecursiveProtectionLiveChain(
        stable=False,
        failure_path=failure_path,
        samples=samples,
    )


def live_count_recursive_regular_file_chain(
    directories: tuple[str | Path, ...] | list[str | Path],
    *,
    quarantine_root: str | Path | None = None,
) -> RecursiveProtectionLiveChain:
    """Count every nested protected ancestor with only two widest-root traversals.

    Recursive-mode authority is a strict source-parent -> ... -> Scan Root chain.
    Scanning each ancestor independently rereads overlapping subtrees. Since the
    widest Scan Root traversal already visits every narrower ancestor, one sampled
    pass can accumulate exact counts for the whole chain. We perform two freshly
    reacquired descriptor-bound/no-follow passes, compare every ancestor count, and
    finally rebind every protected directory to the identity captured before the
    passes. No result is reused across Execute items.
    """

    if not directories:
        return RecursiveProtectionLiveChain(stable=False, failure_path=None, samples=())

    raw_paths = tuple(str(path) for path in directories)
    normalized_paths = tuple(os.path.normpath(path) for path in raw_paths)
    for raw, normalized in zip(raw_paths, normalized_paths):
        if not os.path.isabs(raw) or raw != normalized:
            return _unstable_live_chain(
                normalized_paths,
                failure_path=raw,
            )

    if len(set(normalized_paths)) != len(normalized_paths):
        return _unstable_live_chain(
            normalized_paths,
            failure_path=normalized_paths[0],
        )

    scan_root = normalized_paths[-1]
    for index, path in enumerate(normalized_paths):
        try:
            if os.path.commonpath([path, scan_root]) != scan_root:
                return _unstable_live_chain(
                    normalized_paths,
                    failure_path=path,
                )
            if index + 1 < len(normalized_paths):
                parent = normalized_paths[index + 1]
                if os.path.commonpath([path, parent]) != parent:
                    return _unstable_live_chain(
                        normalized_paths,
                        failure_path=path,
                    )
        except ValueError:
            return _unstable_live_chain(
                normalized_paths,
                failure_path=path,
            )

    identities: dict[str, tuple[int, int]] = {}
    for path in normalized_paths:
        opened = _open_absolute_directory_nofollow(path)
        if opened is None:
            return _unstable_live_chain(
                normalized_paths,
                failure_path=path,
                identities=identities,
            )
        fd, st = opened
        try:
            identities[path] = (int(st.st_dev), int(st.st_ino))
        finally:
            os.close(fd)

    excluded_relative_path = _relative_reserved_quarantine_path(
        scan_root,
        quarantine_root,
    )
    if excluded_relative_path == ".":
        return _unstable_live_chain(
            normalized_paths,
            failure_path=scan_root,
            identities=identities,
        )

    protected_relative_dirs: list[str] = []
    for path in normalized_paths:
        relative = os.path.relpath(path, scan_root)
        if relative == ".":
            protected_relative_dirs.append(".")
            continue
        parts = Path(relative).parts
        if not parts or any(part in ("", ".", "..") for part in parts):
            return _unstable_live_chain(
                normalized_paths,
                failure_path=path,
                identities=identities,
            )
        protected_relative_dirs.append("/".join(parts))
    protected_relative_tuple = tuple(protected_relative_dirs)

    def collect_pass() -> tuple[int, ...] | None:
        opened = _open_absolute_directory_nofollow(scan_root)
        if opened is None:
            return None
        root_fd, root_st = opened
        expected_root = identities[scan_root]
        if (
            int(root_st.st_dev) != expected_root[0]
            or int(root_st.st_ino) != expected_root[1]
        ):
            os.close(root_fd)
            return None
        return _count_live_regular_files_chain_pass(
            root_fd,
            protected_relative_dirs=protected_relative_tuple,
            excluded_relative_path=excluded_relative_path,
        )

    first_counts = collect_pass()
    if first_counts is None:
        return _unstable_live_chain(
            normalized_paths,
            failure_path=scan_root,
            identities=identities,
        )

    second_counts = collect_pass()
    if second_counts is None:
        return _unstable_live_chain(
            normalized_paths,
            failure_path=scan_root,
            identities=identities,
        )

    if first_counts != second_counts:
        mismatch_index = next(
            (
                index
                for index, (first, second) in enumerate(zip(first_counts, second_counts))
                if first != second
            ),
            len(normalized_paths) - 1,
        )
        return _unstable_live_chain(
            normalized_paths,
            failure_path=normalized_paths[mismatch_index],
            identities=identities,
        )

    for path in normalized_paths:
        expected_device, expected_inode = identities[path]
        if not _directory_binding_matches(path, expected_device, expected_inode):
            return _unstable_live_chain(
                normalized_paths,
                failure_path=path,
                identities=identities,
            )

    samples = tuple(
        (
            path,
            RecursiveProtectionLiveCount(
                count=int(second_counts[index]),
                stable=True,
                device=identities[path][0],
                inode=identities[path][1],
            ),
        )
        for index, path in enumerate(normalized_paths)
    )
    return RecursiveProtectionLiveChain(
        stable=True,
        failure_path=None,
        samples=samples,
    )
