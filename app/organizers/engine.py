from __future__ import annotations

from dataclasses import asdict, dataclass
import os
from pathlib import Path
import re
from typing import Any, Iterable

from app.batch.stats import format_size
from app.organizers.planner import detect_rename_cycles_and_sort
from app.organizers.templates import render_template, safe_apply_cleanup_pattern
from app.path_safety import require_allowed_path
from app.utils.sorting import natural_sort_key


@dataclass
class DirectoryStats:
    images: int = 0
    videos: int = 0
    files: int = 0
    folders: int = 0
    total_bytes: int = 0


@dataclass
class OrganizerProposal:
    source: str
    target: str
    images: int
    videos: int
    files: int
    folders: int
    total_bytes: int
    preserved_tags: list[str]
    has_suspicious_tag: bool
    changed: bool
    conflict: bool
    conflict_reason: str | None = None
    expected_mtime_order: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def collect_directory_stats(
    path: Path,
    image_extensions: set[str],
    video_extensions: set[str],
) -> DirectoryStats:
    """Collect image, video, file, folder count and total bytes in directory."""
    stats = DirectoryStats()
    for current, dirnames, filenames in os.walk(path, followlinks=False):
        curr_p = Path(current)
        kept_dirs = []
        for d in dirnames:
            p = curr_p / d
            if p.is_symlink():
                continue
            kept_dirs.append(d)
        dirnames[:] = kept_dirs
        stats.folders += len(kept_dirs)

        for f in filenames:
            p = curr_p / f
            if p.is_symlink():
                continue
            try:
                st = p.stat(follow_symlinks=False)
            except OSError:
                continue
            stats.files += 1
            stats.total_bytes += st.st_size
            ext = p.suffix.lstrip(".").lower()
            if ext in image_extensions:
                stats.images += 1
            if ext in video_extensions:
                stats.videos += 1
    return stats


def collect_tree_stats_bottom_up(
    root: Path,
    image_extensions: set[str],
    video_extensions: set[str],
) -> tuple[dict[Path, DirectoryStats], int, list[Path]]:
    """
    Single-pass tree traversal with bottom-up aggregation.
    Every file is stat'ed exactly once.
    Returns:
        (subtree_stats_by_dir, unique_total_bytes, candidate_dirs)
    """
    direct_stats: dict[Path, dict[str, Any]] = {}
    candidate_dirs: list[Path] = []
    unique_total_bytes = 0

    for current, dirnames, filenames in os.walk(root, followlinks=False):
        curr_p = Path(current)
        kept_dirs = []
        for d in dirnames:
            p = curr_p / d
            if p.is_symlink():
                continue
            kept_dirs.append(d)
            candidate_dirs.append(p)
        dirnames[:] = kept_dirs

        d_img = 0
        d_vid = 0
        d_files = 0
        d_bytes = 0

        for f in filenames:
            fp = curr_p / f
            if fp.is_symlink():
                continue
            try:
                st = fp.stat(follow_symlinks=False)
            except OSError:
                continue

            f_size = st.st_size
            d_files += 1
            d_bytes += f_size
            if curr_p != root:
                unique_total_bytes += f_size

            ext = fp.suffix.lstrip(".").lower()
            if ext in image_extensions:
                d_img += 1
            if ext in video_extensions:
                d_vid += 1

        direct_stats[curr_p] = {
            "images": d_img,
            "videos": d_vid,
            "files": d_files,
            "total_bytes": d_bytes,
            "subdirs": [curr_p / d for d in kept_dirs],
        }

    # Bottom-up aggregation: process from deepest to shallowest
    sorted_dirs = sorted(direct_stats.keys(), key=lambda p: len(p.parts), reverse=True)
    subtree_stats: dict[Path, DirectoryStats] = {}

    for d in sorted_dirs:
        ds = direct_stats[d]
        images = ds["images"]
        videos = ds["videos"]
        files = ds["files"]
        total_bytes = ds["total_bytes"]
        folders = 0

        for child in ds["subdirs"]:
            folders += 1
            if child in subtree_stats:
                c_st = subtree_stats[child]
                images += c_st.images
                videos += c_st.videos
                files += c_st.files
                total_bytes += c_st.total_bytes
                folders += c_st.folders

        subtree_stats[d] = DirectoryStats(
            images=images,
            videos=videos,
            files=files,
            folders=folders,
            total_bytes=total_bytes,
        )

    return subtree_stats, unique_total_bytes, candidate_dirs


def clean_base_name(name: str, cleanup_patterns: list[str]) -> str:
    """Strip old trailing statistics suffixes using configured cleanup regex patterns."""
    value = name.rstrip()
    if not cleanup_patterns:
        return value
    while True:
        stripped = value
        for pattern in cleanup_patterns:
            if pattern.strip():
                stripped = safe_apply_cleanup_pattern(stripped, pattern, "").rstrip()
        if stripped == value:
            return value
        value = stripped


def generate_organizer_proposals(
    root: Path | str,
    *,
    allowed_roots: Iterable[Path | str],
    image_extensions: list[str],
    video_extensions: list[str],
    rename_template: str,
    statistics_template: str,
    preserve_tags: list[str],
    cleanup_patterns: list[str],
    numbering_mode: str = "none",
    numbering_start: int = 1,
    numbering_padding: int = 3,
    mtime_mode: str = "none",
    mtime_delay_seconds: float = 2.0,
    recursive: bool = False,
) -> tuple[dict[str, Any], list[OrganizerProposal]]:
    """
    Pure read-only calculation of rename proposals and conflict detection.
    Never modifies, renames, touches, or deletes any files on disk.
    """
    safe_root = require_allowed_path(root, allowed_roots)
    if not safe_root.is_dir():
        raise ValueError(f"Not a directory: {safe_root}")

    img_exts = {e.lstrip(".").lower() for e in image_extensions}
    vid_exts = {e.lstrip(".").lower() for e in video_extensions}

    # Discover candidate subdirectories and compute stats
    candidates: list[Path] = []
    subtree_stats: dict[Path, DirectoryStats] = {}
    unique_total_bytes = 0

    if recursive:
        subtree_stats, unique_total_bytes, candidates = collect_tree_stats_bottom_up(
            safe_root, img_exts, vid_exts
        )
        candidates.sort(key=lambda p: (len(p.parts), natural_sort_key(p.name)))
    else:
        with os.scandir(safe_root) as it:
            for entry in it:
                try:
                    if entry.is_dir(follow_symlinks=False):
                        candidates.append(Path(entry.path))
                except OSError:
                    continue
        candidates.sort(key=lambda p: natural_sort_key(p.name))
        for c in candidates:
            st = collect_directory_stats(c, img_exts, vid_exts)
            subtree_stats[c] = st
            unique_total_bytes += st.total_bytes

    source_set = {str(p.resolve()) for p in candidates}
    claimed_targets: dict[str, Path] = {}
    proposals: list[OrganizerProposal] = []

    total_directories = len(candidates)
    changed_directories = 0
    total_conflicts = 0

    for idx, source in enumerate(candidates):
        stats = subtree_stats.get(source, DirectoryStats())

        # 1. Clean old tail
        cleaned_base = clean_base_name(source.name, cleanup_patterns)

        # 2. Check preserved tags
        matched_tags = [t for t in preserve_tags if t and t in source.name]
        has_suspicious_tag = bool(matched_tags)

        # 3. Format index
        if numbering_mode == "sequential":
            index_str = str(numbering_start + idx).zfill(numbering_padding)
        else:
            index_str = ""

        # 4. Render statistics_template
        stat_context = {
            "name": cleaned_base,
            "images": stats.images,
            "videos": stats.videos,
            "files": stats.files,
            "files_count": stats.files,
            "folders": stats.folders,
            "size": format_size(stats.total_bytes),
        }
        stat_str = render_template(statistics_template, stat_context).strip()

        # 5. Render rename_template
        rename_context = {
            "name": cleaned_base,
            "index": index_str,
            "statistics": stat_str,
            "images": stats.images,
            "videos": stats.videos,
            "files": stats.files,
            "files_count": stats.files,
            "folders": stats.folders,
            "size": format_size(stats.total_bytes),
            "parent": source.parent.name,
            "extension": "",
        }
        target_name = render_template(rename_template, rename_context).strip()

        # Ensure preserved tags are not accidentally lost if cleaned base didn't retain them
        for tag in matched_tags:
            if tag not in target_name:
                if stat_str and stat_str in target_name:
                    target_name = target_name.replace(stat_str, f"{tag} {stat_str}").strip()
                else:
                    target_name = f"{target_name} {tag}".strip()

        target = source.with_name(target_name)
        changed = (target != source)
        if changed:
            changed_directories += 1

        # Conflict Detection (using full normalized path)
        conflict = False
        conflict_reason: str | None = None

        if not target_name or any(c in target_name for c in "/\0"):
            conflict = True
            conflict_reason = "目标名称为空或包含非法路径分隔符"
        else:
            # 1. NAME_MAX validation in bytes (BEFORE any exists/stat/resolve call)
            try:
                name_bytes = len(os.fsencode(target_name))
                try:
                    name_max = os.pathconf(source.parent, "PC_NAME_MAX")
                except (OSError, AttributeError, ValueError):
                    name_max = 255
                if name_bytes > name_max:
                    conflict = True
                    conflict_reason = f"目标目录名称超过文件系统限制 ({name_bytes} bytes > {name_max} bytes)"
            except OSError as exc:
                conflict = True
                conflict_reason = f"目标目录名称超过文件系统限制: {exc}"

            # 2. PATH_MAX validation in bytes
            if not conflict:
                try:
                    path_bytes = len(os.fsencode(str(target)))
                    try:
                        path_max = os.pathconf(source.parent, "PC_PATH_MAX")
                    except (OSError, AttributeError, ValueError):
                        path_max = 4096
                    if path_bytes > path_max:
                        conflict = True
                        conflict_reason = f"目标总路径超过文件系统限制 ({path_bytes} bytes > {path_max} bytes)"
                except OSError as exc:
                    conflict = True
                    conflict_reason = f"目标总路径超过文件系统限制: {exc}"

            # 3. Parent path within ALLOWED_ROOTS
            if not conflict:
                try:
                    require_allowed_path(target.parent, allowed_roots)
                except Exception as exc:
                    conflict = True
                    conflict_reason = f"目标路径越界: {exc}"

            # 4. Check if lexical target itself is a symlink
            if not conflict:
                try:
                    if target.is_symlink():
                        conflict = True
                        conflict_reason = "目标路径已存在同名符号链接 (symlink)"
                except OSError as exc:
                    conflict = True
                    conflict_reason = f"目标路径无法访问: {exc}"

            # 5. Check target existence and collisions safely
            if not conflict:
                try:
                    target_exists = target.exists()
                except OSError as exc:
                    conflict = True
                    conflict_reason = f"目标路径访问出错: {exc}"
                    target_exists = False

                if not conflict:
                    try:
                        target_resolved_str = str(target.resolve() if target_exists else target)
                        source_resolved_str = str(source.resolve())
                    except OSError as exc:
                        conflict = True
                        conflict_reason = f"解析目标路径失败: {exc}"
                        target_resolved_str = str(target)
                        source_resolved_str = str(source)

                if not conflict:
                    if target_resolved_str in claimed_targets:
                        conflict = True
                        conflict_reason = f"目标重命名碰撞: 与目录 '{claimed_targets[target_resolved_str].name}' 重名"
                    elif target_exists and target_resolved_str != source_resolved_str and target_resolved_str not in source_set:
                        conflict = True
                        conflict_reason = f"磁盘上已存在目标同名文件或目录: '{target.name}'"
                    else:
                        claimed_targets[target_resolved_str] = source

        if conflict:
            total_conflicts += 1

        proposals.append(
            OrganizerProposal(
                source=str(source),
                target=str(target),
                images=stats.images,
                videos=stats.videos,
                files=stats.files,
                folders=stats.folders,
                total_bytes=stats.total_bytes,
                preserved_tags=matched_tags,
                has_suspicious_tag=has_suspicious_tag,
                changed=changed,
                conflict=conflict,
                conflict_reason=conflict_reason,
                expected_mtime_order=(idx + 1) if mtime_mode == "ordered" else None,
            )
        )

    # Detect cycle conflicts among changed proposals
    changed_for_cycle = [
        {"source": p.source, "target": p.target}
        for p in proposals
        if p.changed and not p.conflict
    ]
    _, cycle_sources = detect_rename_cycles_and_sort(changed_for_cycle)
    if cycle_sources:
        for p in proposals:
            if p.source in cycle_sources and not p.conflict:
                p.conflict = True
                p.conflict_reason = "检测到循环重命名依赖 (cycle dependency)"
                total_conflicts += 1

    summary = {
        "total_directories": total_directories,
        "changed_directories": changed_directories,
        "conflicts": total_conflicts,
        "total_bytes": unique_total_bytes,
    }
    return summary, proposals
