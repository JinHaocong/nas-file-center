"""Read-only discovery and planning for the two media organizer modes."""
from __future__ import annotations

import os
import re
import stat
from collections import Counter, OrderedDict
from contextvars import ContextVar
from datetime import date
from itertools import islice
from pathlib import Path
from typing import Callable, Iterator, NamedTuple
from unicodedata import name as unicode_name
from unicodedata import normalize

from app.batch.file_rename import _open_directory_nofollow
from app.batch.media_organizer_archive import is_repeated_archive, preview_repeated_archive
from app.batch.media_package_naming import MEDIA_BUCKET_PATTERN, numbered_name
from app.batch.media_package_organizer import (
    MAX_DEPTH, MAX_FILES_PER_GROUP, MAX_PACKAGE_DIRECTORIES, MAX_PACKAGE_FILES, MAX_SCOPE_ENTRIES_PER_DIRECTORY,
    LIFT_LUOLCY_BUCKETS, PROMOTE_NUMBERED_PHOTO_GROUPS,
    _author_media_row, _classify, _input_fingerprint, _luolcy_author_inventory, _package_path, _plan_luolcy_bucket_lift,
    _size_label,
    _walk_package,
    iter_media_package_discovery, plan_media_layout,
)
from app.path_safety import require_allowed_path, require_unreserved_path

_LEGACY_BUCKET = re.compile(r"(?:p|v)(?:_?[1-9]\d*)?|other", re.I)
_LEGACY_COUNTED_BUCKET = re.compile(
    r"(?P<label>pic|video)\s+\[(?P<count>[1-9][0-9]{0,2})\s*(?P<kind>[pv])\s*-\s*"
    r"[0-9]+(?:\.[0-9]+)?\s*(?:[kmgt]i?b|b)\]", re.I,
)
_OTHER_BUCKET = re.compile(r"other \[\d+ [^/]+\]", re.I)
_CALENDAR_DIRECTORY = re.compile(
    r"(?:19|20)\d{2}|(?:\d{2}|\d{4})(?:"
    r"[-_.]?(?:0[1-9]|1[0-2])(?:[-_.]?(?:0[1-9]|[12]\d|3[01]))?"
    r"|年(?:0?[1-9]|1[0-2])月(?:(?:0?[1-9]|[12]\d|3[01])日)?)"
)
_CALENDAR_DAY = re.compile(
    r"(?:\d{2}|\d{4})(?:[-_.]?(?:0[1-9]|1[0-2])[-_.]?(?:0[1-9]|[12]\d|3[01])"
    r"|年(?:0?[1-9]|1[0-2])月(?:0?[1-9]|[12]\d|3[01])日)"
)
_CALENDAR_MONTH = re.compile(r"(?:\d{2}|\d{4})(?:[-_.]?(?:0[1-9]|1[0-2])|年(?:0?[1-9]|1[0-2])月)")
_SHORT_CALENDAR_LABEL = re.compile(
    r"(?:\d{2,4}[-_.年])?(?:0?[1-9]|1[0-2])(?:[-_.月](?:0?[1-9]|[12]\d|3[01])[日号]?|月份?)"
    r"|(?:\d{2}|\d{4})[-_.](?:0?[1-9]|1[0-2])"
)
_RESOLUTION_NAME = re.compile(r"(?:[248]k|[0-9]{3,4}p)", re.I)
_DEFAULT_FOLDER = re.compile(r"新建文件夹(?:\s*\(\d+\))?")
_AMBIGUOUS = re.compile(r"\d{1,3}|" + _DEFAULT_FOLDER.pattern, re.I)
_NUMBERED_LEAF = re.compile(r"[0-9]{1,3}")
_PACK_VOLUME_WORK = re.compile(
    r"(?P<series>.+?)(?:\s*[-–—]\s*|\s+)pack\s*(?:\((?P<bracketed>[0-9]+)\)|(?P<plain>[0-9]+))", re.I,
)
_COLLECTION_CONTEXT = re.compile(
    r"合集|全集|图包|作品|\b(?:collection|album)\b|\bno[.\s_-]*\d+\b|\b[a-z]+\d+-\d+\b",
    re.I,
)
_WORK_FOLDER_MARKER = re.compile(
    r"\b(?:ex)?vol[.\s_-]*[0-9]+|[\[【][^\]】]*[0-9]+\s*(?:p|v|张|图|视频)", re.I,
)
_BRACKETED_LABEL = re.compile(r"[\[【]([^\]】]*)[\]】]")
_MEDIA_COUNT_LABEL = re.compile(r"[0-9]+\s*(?:p|v|张|图|视频)", re.I)
_MEDIA_COUNT_SIZE_SUFFIX = r"(?:[\s/\-／]+[0-9]+(?:\.[0-9]+)?\s*(?:[kmgt]i?b|b|[kmgt]))?"
_PHOTO_PACK_TOTAL = re.compile(r"\s*([0-9]+)\s*p" + _MEDIA_COUNT_SIZE_SUFFIX + r"\s*", re.I)
_MIXED_WORK_TOTAL = re.compile(r"(?<![0-9a-z])([0-9]+)\s*p\s*(?:[+／/\-]\s*)?([0-9]+)\s*v(?![0-9a-z])", re.I)
_ADDITIONAL_WORK_COUNT = re.compile(r"[0-9]+\s*(?:[pv](?![0-9a-z])|张(?:图)?|图|个视频|视频)", re.I)
_WORK_SEQUENCE_LABEL = re.compile(r"(?<![0-9a-z])(?:exvol|vol|no)[.\s_-]*[0-9]+", re.I)
_SPLIT_WORK_TOTAL = re.compile(
    r"\s*([0-9]+)\s*p(?:\s*[+／/\-])?\s*([0-9]+)\s*v"
    r"(?:[\s/\-／]*[0-9]+(?:\.[0-9]+)?\s*(?:[kmgt]i?b|b|[kmgt]))?\s*", re.I,
)
_WORK_PHOTO_RANGE = re.compile(
    r"(?P<title>.+?)\s*[【\[]\s*(?:照片|图片|圖片|图|圖)\s*"
    r"(?P<first>[0-9]+)\s*[-~～至]\s*(?P<last>[0-9]+)\s*[】\]]",
)
_WORK_VIDEO_PART = re.compile(r"(?P<title>.+?)\s*[【\[]\s*视频(?:\s*[+＋]\s*花絮)?\s*[】\]]")
_WORK_R16_JPEG = re.compile(r"(?P<stem>.+?(?<![a-z0-9])[a-z]{1,6}-[0-9]{2,5})-R16-JPE?G", re.I)
_SAME_ISSUE_TITLE = re.compile(r"【[^【】0-9]+([1-9][0-9]{0,2})】")
_PICTURE_SERIES_LABEL = re.compile(r"图[1-9][0-9]?")
_NUMBERED_WORK_CODE = re.compile(r"[a-z][0-9]+-[0-9]+", re.I)
_DATED_EXPORT_LABEL = re.compile(
    r"(?:0?[1-9]|1[0-2])[.月](?:0?[1-9]|[12][0-9]|3[01])号"
    r"【([1-9][0-9]*)v\s+([1-9][0-9]*)p" + _MEDIA_COUNT_SIZE_SUFFIX + r"】", re.I,
)
_EXPORT_MONTH_DAY = r"[-_.](?P<month>[0-9]{1,2})[-_.](?P<day>[0-9]{1,2})"
_EXPORT_WORK_DATE = re.compile(r"(?P<year>(?:19|20)?[0-9]{2})" + _EXPORT_MONTH_DAY + r"(?![0-9])")
_DATED_EXPORT_WRAPPER = re.compile(
    r"(?P<year>(?:19|20)[0-9]{2})" + _EXPORT_MONTH_DAY + r"[-_ ]+(?=[a-z0-9]*[0-9])[a-z0-9]{6,32}", re.I,
)
_PAGED_EXPORT_WRAPPER = re.compile(
    r"(?:✅\s*)?全部文件\s*第\s*(?P<first>[1-9][0-9]*)(?:[_-](?P<last>[1-9][0-9]*))?\s*页\s*[-－]\s*[0-9]{10,32}"
)
_DATED_WORK_ALIAS = re.compile(
    r"(?P<date>[0-9]{2}\.\d{2}\.\d{2})\s*(?P<title>[^()\[\]【】]+?)"
    r"\s*(?:\((?P<round>[^()]+)\)|【(?P<wide>[^【】]+)】|\[(?P<square>[^\[\]]+)\])\s*[★☆]?",
)
_PUBLISHED_WORK_DATE = re.compile(r"[0-9]{2}\.(?:0[1-9]|1[0-2])\.(?:0[1-9]|[12][0-9]|3[01])(?![0-9])")
_PUBLISHED_ARCHIVE_MONTH = re.compile(r"(?P<month>(?:19|20)[0-9]{2}\.[0-9]{2})(?:【[^【】\[\]]+】|\[[^【】\[\]]+\])")
_PUBLISHED_MONTH_DAY_ALIAS = re.compile(r"(?P<credit>[^\W\d_]{2,12})\s*(?P<stamp>[0-9]{2}\.[0-9]{2})")
_PUBLISHED_WORK_COUNTS = re.compile(
    r"(?<![0-9a-z])" + _SPLIT_WORK_TOTAL.pattern + r"(?=$|\s|[()】\]])", re.I,
)
_PUBLISHED_WORK_TRAILER = re.compile(r"\s*(?:\([^()\[\]【】]+\))?\s*[★☆]?\s*")
_WORK_COUNT_BRACKETS = {"(": ")", "【": "】", "[": "]"}
_WORK_VARIANT_LABEL = re.compile(
    r"原版|原档|压缩|水印|无修|無修|未修|修复版|精华版|完整版|加长版|短版|长版"
    r"|版(?:本)?(?=$|[\s\]】）)_-])"
    r"|(?:^|[^0-9a-z])(?:r[0-9]+|[248]k|[0-9]{3,4}p)(?![0-9a-z])", re.I,
)
_VERSION_NAMES = frozenset({"4k", "pt", "原图无水印", "精华版", "修复版"})
_MIXED_WRAPPER_REASON = "分类包装里的散文件归属待确认"
_AMBIGUOUS_DIRECTORY_REASON = "Ambiguous directory role"
_NUMBERED_WORK_CONTAINER_CANDIDATE = "Numbered work container candidate"
DIRECT_MEDIA_SCOPE = "direct-media"
_FINISH_REPEATED_ARCHIVE = "Finish repeated archive"
_PHOTO_ALIASES = frozenset({
    "图片", "图", "照片", "photo", "photos", "image", "images", "picture", "pictures", "pic",
})
_PRIVATE_UNLOCK_SUPPLEMENTS = frozenset({"私讯解锁", "私訊解鎖"})
_COUNTED_PHOTO_SUPPLEMENTS = _PRIVATE_UNLOCK_SUPPLEMENTS | {"私讯", "私訊", "封面", "封面图", "封面圖"}
_ALIASES = _PHOTO_ALIASES | {"视频", "video", "videos"}
_VIDEO_WRAPPER_ALIASES = frozenset({"视频", "video", "videos"})
_NUMBERED_TITLED_WORK = re.compile(r"[1-9][0-9]{0,2}\s*(?P<title>[^\W\d_][\w ]+)")
_EPISODE_TITLE = re.compile(
    r"(?:(?P<series>[^/]*?)第\s*)?(?P<ordinal>[0-9]{1,4}|[?？])弹(?:\s*[-－—_：:]\s*|\s+)\S.*"
)
_EPISODE_BOUNDARY = re.compile(r"(?:^|第)\s*[0-9]{1,4}\s*(?:弹|集|期|话|話)(?![0-9])")
_EPISODE_ARCHIVES = frozenset({"old", "archive", "backup", "bak", "旧版", "备份"})
_JPEG_LABELS = frozenset({"jpg", "jpeg"})
_JPEG_EXTENSIONS = frozenset({".jpg", ".jpeg", ".jfif"})
_TYPED_WRAPPER_KINDS = {"movie": "V", "img": "P", "gif": "P", "selfies": "P", "jpg": "P", "jpeg": "P"}
_FANTIA_COLLECTION = re.compile(r"(?<![a-z0-9])fantia(?![a-z0-9])", re.I | re.ASCII)
_FANTIA_POST_COLLECTION = re.compile(
    r"(?<![a-z0-9])fantia(?:(?![a-z0-9])|(?=(?:0?[1-9]月|1[0-2]月|[0-9]{1,5}\s*日[圓圆元])(?![a-z0-9])))",
    re.I | re.ASCII,
)
_FANTIA_TIER = re.compile(r"\$(?P<amount>[0-9]+)_.*")
_FANTIA_POST_ID = re.compile(r"[0-9]{7}")
_FANTIA_POST_STAMP = re.compile(
    r"(?:"
    r"(?:0[1-9]|[12][0-9]|3[01])_(?:[01][0-9]|2[0-3])[0-5][0-9]_"
    r"|(?:(?:19|20)[0-9]{2})?(?:0[1-9]|1[0-2])(?:0[1-9]|[12][0-9]|3[01])\s+"
    r"|(?P<iso_date>(?:19|20)[0-9]{2}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01]))"
    r"(?:\s+|_(?:(?:[01][0-9]|2[0-3])[0-5][0-9]_)?)"
    r")(?P<title>.+)",
)
_FANTIA_POST_CLOCK = re.compile(r"(?:[01][0-9]|2[0-3]):?[0-5][0-9](?::[0-5][0-9])?")
_FANTIA_MIXED_POST_TOTAL = re.compile(r"\s*" + _MIXED_WORK_TOTAL.pattern + _MEDIA_COUNT_SIZE_SUFFIX + r"\s*", re.I)
_FANTIA_FREE_COVER_NAMES = frozenset({"無料&封面", "無料＆封面"})
_FANTIA_PREVIEW_NAMES = _FANTIA_FREE_COVER_NAMES | {"無料", "封面", "cover"}
_FANTIA_NUMBERED_PHOTO_PART = re.compile(r"(?:写真|寫真)\s*([1-9][0-9]*)")
_FANTIA_PHOTO_PART_LABEL = re.compile(r"(?:写真|寫真)[\W_]*")
_PREVIEW_CACHE_DIRECTORIES = 128
_PREVIEW_CACHE_ENTRIES = 16_384


def _fantia_collection(path: Path) -> bool:
    return _FANTIA_COLLECTION.search(path.name) is not None


def _fantia_post_title(path: Path) -> str | None:
    """Read a post title while preserving date-only directories with media counts."""
    # Adjacent month and price labels prove a post context without changing
    # how ordinary children of the collection are interpreted.
    if not _FANTIA_POST_COLLECTION.search(path.parent.name):
        return None
    stamp = _FANTIA_POST_STAMP.fullmatch(path.name)
    if stamp is None:
        return None
    title = _BRACKETED_LABEL.sub(
        lambda match: "" if _MEDIA_COUNT_LABEL.search(match[1]) else match[0], stamp["title"],
    ).strip().strip("_").strip()
    if not title or (stamp["iso_date"] is not None and _FANTIA_POST_CLOCK.fullmatch(title)):
        return None
    return title


def _is_wrapper(
    parent: Path, name: str, *, device: int | None = None, protected_roots: tuple[Path, ...] = (),
) -> bool:
    """Identify classification folders within works and author-level batches."""
    if device is not None and _FANTIA_TIER.fullmatch(name):
        return _fantia_tier_wrapper(parent, name, device, protected_roots)
    if _fantia_collection(parent):
        # A post may be called P or photos. Only verified output buckets belong to the collection.
        return device is not None and _verified_bucket_kind(parent / name, device) is not None
    if _labelled_bucket_kind(name):
        return True
    if _CALENDAR_DIRECTORY.fullmatch(parent.name) and not any(
        _author_layer(ancestor) and not _CALENDAR_DIRECTORY.fullmatch(ancestor.name)
        for ancestor in parent.parents
    ):
        # A library date's direct children can be authors named P, V or photos.
        return False
    if name == "图包" and device is not None:
        entries = _regular_media_entries(parent / name, device)
        if not entries or any(_classify(filename) != "P" for filename, _ in entries):
            return False
        if _author_layer(parent):
            # A photo pack beside separate works at author level keeps its own boundary.
            return not any(
                peer != name and stat.S_ISDIR(info.st_mode)
                and (not _is_wrapper(parent, peer) or not _pure_wrapper(parent / peer, device, ()))
                for peer, info in _entries(parent, device)
            )
        return True
    if device is not None and name.casefold() in _TYPED_WRAPPER_KINDS:
        return _typed_leaf_wrapper(parent, name, device, protected_roots)
    return bool(_LEGACY_BUCKET.fullmatch(name) or name.casefold() in _ALIASES)


def is_reserved_workspace(path: Path) -> bool:
    """Recognize directories reserved for live or historical organizer stages."""
    return any(part.casefold().startswith(".nfc-") for part in path.parts)


def _checked_scope(unit: Path, allowed_roots: list[Path], quarantine_root: Path | None) -> Path:
    unit = Path(unit)
    if is_reserved_workspace(unit):
        raise ValueError("Reserved organizer workspace cannot be selected")
    if not unit.is_absolute() or unit != require_unreserved_path(
        require_allowed_path(unit, allowed_roots), quarantine_root,
    ):
        raise ValueError("Choose a literal, allowed media directory")
    os.close(_open_directory_nofollow(unit))
    return unit


_DirectoryEntries = list[tuple[str, os.stat_result]]


class _OwnedMediaSources(NamedTuple):
    wrappers: set[str]
    totals: Counter[str]
    photo_range_starts: dict[str, int] | None = None


def _directory_binding(info: os.stat_result) -> tuple[int, ...]:
    return info.st_dev, info.st_ino, info.st_mode, info.st_mtime_ns, info.st_ctime_ns


def _read_entries(fd: int) -> _DirectoryEntries:
    entries = []
    with os.scandir(fd) as stream:
        for entry in stream:
            if len(entries) >= MAX_SCOPE_ENTRIES_PER_DIRECTORY:
                raise ValueError("Media directory entry limit exceeded")
            entries.append((entry.name, entry.stat(follow_symlinks=False)))
    return sorted(entries, key=lambda entry: (entry[0].casefold(), entry[0]))


class _PreviewDirectoryInventory:
    """Keep a bounded cache of directory listings for a single recursive preview."""

    def __init__(self) -> None:
        self._directories: OrderedDict[Path, tuple[tuple[int, ...], _DirectoryEntries]] = OrderedDict()
        self._entry_count = 0

    def read(self, folder: Path, fd: int, info: os.stat_result) -> _DirectoryEntries:
        current = _directory_binding(info)
        previous = self._directories.get(folder)
        if previous is not None:
            binding, entries = previous
            # Entry additions, renames and directory replacement invalidate the listing.
            if current == binding:
                self._directories.move_to_end(folder)
                return entries
            del self._directories[folder]
            self._entry_count -= len(entries)
        entries = _read_entries(fd)
        if len(entries) <= _PREVIEW_CACHE_ENTRIES:
            while (len(self._directories) >= _PREVIEW_CACHE_DIRECTORIES
                   or self._entry_count + len(entries) > _PREVIEW_CACHE_ENTRIES):
                _, (_, evicted) = self._directories.popitem(last=False)
                self._entry_count -= len(evicted)
            self._directories[folder] = (current, entries)
            self._entry_count += len(entries)
        return entries


_preview_inventory: ContextVar[_PreviewDirectoryInventory | None] = ContextVar(
    "media_organizer_preview_inventory", default=None,
)


def _entries(folder: Path, device: int) -> _DirectoryEntries:
    fd = _open_directory_nofollow(folder)
    try:
        info = os.fstat(fd)
        if info.st_dev != device:
            raise ValueError("Cross-device directory")
        inventory = _preview_inventory.get()
        return inventory.read(folder, fd, info) if inventory is not None else _read_entries(fd)
    finally:
        os.close(fd)


def _protected(path: Path, protected_roots: tuple[Path, ...]) -> bool:
    return any(path.is_relative_to(root) for root in protected_roots)


def _resolved_protected_roots(*roots: Path | None) -> tuple[Path, ...]:
    """Use the same physical protection boundary for selection and wrapper traversal."""
    return tuple(Path(root).expanduser().resolve(strict=False) for root in roots if root is not None)


def _author_layer(unit: Path) -> bool:
    """Recognize the author level without mistaking a named work or version for an author."""
    return bool(_CALENDAR_DAY.fullmatch(unit.parent.name)
                and not _COLLECTION_CONTEXT.search(unit.name)
                and unit.name.casefold() not in _VERSION_NAMES)


def _labelled_bucket_kind(name: str) -> str | None:
    match = MEDIA_BUCKET_PATTERN.fullmatch(name)
    if match:
        return match.group("kind").upper()
    return "Other" if _OTHER_BUCKET.fullmatch(name) else None


def _local_wrapper_media_kind(unit: Path) -> str | None:
    """Read the media type of a classification directory that can keep local files."""
    label = unit.name.casefold()
    if (label in _PHOTO_ALIASES or label in {"p", "v"}) and _is_wrapper(unit.parent, unit.name):
        return "V" if label == "v" else "P"
    return None


def _pure_wrapper(folder: Path, device: int, protected_roots: tuple[Path, ...],
                  check_cancelled: Callable[[], None] | None = None) -> bool:
    """Only merge a classification branch whose descendants have no other directory role."""
    pending = [(folder, 1)]
    visited = 0
    while pending:
        current, depth = pending.pop()
        if check_cancelled is not None:
            check_cancelled()
        visited += 1
        if depth > MAX_DEPTH or visited > MAX_PACKAGE_DIRECTORIES:
            return False
        try:
            fd = _open_directory_nofollow(current)
            try:
                if os.fstat(fd).st_dev != device:
                    return False
                # Shape detection can use entry types; the inventory still reads every file identity.
                with os.scandir(fd) as entries:
                    for index, entry in enumerate(entries):
                        if index >= MAX_SCOPE_ENTRIES_PER_DIRECTORY or entry.name.casefold().startswith(".nfc-"):
                            return False
                        if entry.is_dir(follow_symlinks=False):
                            child = current / entry.name
                            if _protected(child, protected_roots) or not _is_wrapper(
                                current, entry.name, device=device, protected_roots=protected_roots,
                            ):
                                return False
                            pending.append((child, depth + 1))
                        elif not entry.is_file(follow_symlinks=False):
                            return False
            finally:
                os.close(fd)
        except (OSError, ValueError):
            return False
    return True


def _layer_media_kinds(unit: Path, entries: list[tuple[str, os.stat_result]], device: int,
                       protected_roots: tuple[Path, ...]) -> tuple[str, ...]:
    """Identify pure local media beside separate works or dated subgroups."""
    author = _author_layer(unit)
    wrapper_kind = _local_wrapper_media_kind(unit)
    if not author and wrapper_kind is None:
        return ()
    direct = {_classify(name) for name, info in entries if stat.S_ISREG(info.st_mode)}
    if direct and (len(direct) != 1 or "Other" in direct):
        return ()
    children = [unit / name for name, info in entries
                if stat.S_ISDIR(info.st_mode) and info.st_dev == device
                and not _protected(unit / name, protected_roots)]
    kinds = direct
    if not kinds:
        # A later scan sees the published buckets at this level. Keep existing
        # Other buckets with them, and fall back when a bucket needs reclassification.
        labelled = [child for child in children
                    if _labelled_bucket_kind(child.name)]
        kinds = {_verified_bucket_kind(child, device) for child in labelled}
        if None in kinds:
            return ()
    media_kinds = kinds - {"Other"}
    if not media_kinds or (wrapper_kind is not None and media_kinds != {wrapper_kind}):
        return ()
    if wrapper_kind is not None and unit.name.casefold() in {"p", "v"} and any(
        _is_wrapper(unit, child.name, device=device, protected_roots=protected_roots)
        and _verified_bucket_kind(child, device) not in kinds
        for child in children
    ):
        return ()
    if any(
        not _is_wrapper(unit, child.name, device=device, protected_roots=protected_roots)
        or not _pure_wrapper(child, device, protected_roots)
        for child in children
    ):
        return tuple(sorted(kinds))
    return ()


def _calendar_author_layer(unit: Path) -> bool:
    """Recognize YYMM/YYMMDD/author without guessing from a date alone."""
    day = unit.parent.name
    return (len(day) == 6 and day[:4] == unit.parent.parent.name
            and _author_layer(unit) and not _append_calendar_boundary(unit.name))


def _scoped_bucket_kind(path: Path, device: int, protected_roots: tuple[Path, ...]) -> str | None:
    """Check that a sized bucket's direct files agree with its labelled class and counts."""
    match = MEDIA_BUCKET_PATTERN.fullmatch(path.name)
    if match is None or _protected(path, protected_roots):
        return None
    kind = match["kind"].upper()
    files = _regular_media_entries(path, device)
    if (not files or any(_classify(name) != kind or _protected(path / name, protected_roots)
                         for name, _ in files)):
        return None
    actual = f"[{len(files)} {_size_label(sum(info.st_size for _, info in files))}]"
    return kind if actual == match["label"] else None


def _direct_media_selection(
    unit: Path, entries: _DirectoryEntries, device: int, protected_roots: tuple[Path, ...],
) -> tuple[tuple[str, ...], dict[str, str]]:
    """Select direct P/V media and only classification children owned by this layer."""
    numbered = (_NUMBERED_LEAF.fullmatch(unit.name) is not None
                and any(_calendar_author_layer(parent) for parent in unit.parents))
    author = _calendar_author_layer(unit)
    wrapper = _local_wrapper_media_kind(unit)
    if (not (numbered or author or wrapper)
            or any(root.is_relative_to(unit) for root in protected_roots)):
        return (), {}
    kinds = set()
    children = []
    for name, info in entries:
        path = unit / name
        if info.st_dev != device or is_reserved_workspace(path):
            return (), {}
        if stat.S_ISDIR(info.st_mode):
            children.append(name)
            continue
        if not stat.S_ISREG(info.st_mode) or _protected(path, protected_roots):
            return (), {}
        kind = _classify(name)
        if kind in {"P", "V"}:
            kinds.add(kind)
        elif not (author and not path.suffix):
            return (), {}
    if wrapper and kinds - {wrapper}:
        return (), {}
    if author and not (numbered or wrapper) and sum(
        not _labelled_bucket_kind(name) and not _is_wrapper(unit, name)
        for name in children
    ) < 2:
        return (), {}
    buckets = {}
    for name in children:
        kind = _scoped_bucket_kind(unit / name, device, protected_roots)
        if kind and (wrapper is None or kind == wrapper):
            buckets[name] = kind
    if wrapper == "V" and not buckets and kinds == {"V"}:
        incoming = _video_wrapper_append_source(unit, entries, children, device, protected_roots)
        if incoming is not None:
            buckets[incoming] = "V"
    # A numbered work can own one pure, explicitly complementary media leaf,
    # such as 024's Video alongside direct photos. Leave other roles independent.
    if numbered and len(children) == len(kinds) == 1 and not buckets:
        name, = children
        branch = unit / name
        folded = name.casefold()
        label = "P" if folded in _PHOTO_ALIASES | {"p"} else "V" if folded in {"v", "video", "videos", "视频"} else None
        if label and label not in kinds and not _protected(branch, protected_roots):
            files = _regular_media_entries(branch, device)
            if files and all(_classify(file) == label and not _protected(branch / file, protected_roots)
                             for file, _ in files):
                buckets[name] = label
    kinds.update(buckets.values())
    return tuple(sorted(kinds)), buckets


def _repeated_work_wrapper(unit: Path, entries: list[tuple[str, os.stat_result]],
                           device: int, protected_roots: tuple[Path, ...]) -> Path | None:
    """Find the media leaf at the end of a chain of exact-name wrappers."""
    if (len(entries) != 1 or _append_calendar_boundary(unit.name)
            or _fantia_collection(unit)
            or unit.name.casefold() in _VERSION_NAMES or _WORK_VARIANT_LABEL.search(unit.name)
            or _author_layer(unit)
            or _AMBIGUOUS.fullmatch(unit.name) or _is_wrapper(unit.parent, unit.name)
            or unit.name == "图包"):
        return None
    inner = unit
    try:
        for _ in range(MAX_DEPTH):
            if len(entries) != 1:
                break
            name, info = entries[0]
            if name != unit.name or not stat.S_ISDIR(info.st_mode):
                break
            child = inner / name
            if info.st_dev != device or _protected(child, protected_roots):
                return None
            inner = child
            entries = _entries(inner, device)
        if inner != unit and entries and all(
            info.st_dev == device and not name.casefold().startswith(".nfc-")
            and not _protected(inner / name, protected_roots)
            and ((stat.S_ISREG(info.st_mode) and _classify(name) in {"P", "V"})
                 or (stat.S_ISDIR(info.st_mode) and _verified_bucket_kind(inner / name, device)))
            for name, info in entries
        ):
            return inner
    except (OSError, ValueError):
        return None
    return None


def _semantic_inventory(
    unit: Path, protected_roots: tuple[Path, ...],
    directories: set[Path] | None = None,
    local_media_kinds: tuple[str, ...] = (), *, whole_author: bool = False,
    local_scope: str | None = None,
    check_cancelled: Callable[[], None] | None = None,
) -> Iterator[dict]:
    """Read the semantic unit, including its descendants for a whole-author plan."""
    if _protected(unit, protected_roots):
        raise ValueError(f"Protected media directory: {unit}")
    folders = [(unit, 0)]
    device = os.lstat(unit).st_dev
    files = directory_count = 0
    repeated = None
    owned_sources = None
    owned_totals: Counter[str] = Counter()
    local_children: dict[str, str] = {}
    while folders:
        if check_cancelled is not None:
            check_cancelled()
        folder, depth = folders.pop()
        directory_count += 1
        if depth > MAX_DEPTH or directory_count > MAX_PACKAGE_DIRECTORIES:
            raise ValueError("Classification wrapper traversal limit exceeded")
        if directories is not None:
            directories.add(folder)
        children = []
        entries = _entries(folder, device)
        if not depth and local_scope == DIRECT_MEDIA_SCOPE:
            live_kinds, local_children = _direct_media_selection(unit, entries, device, protected_roots)
            if live_kinds != local_media_kinds:
                raise ValueError("Direct media scope changed since preview")
        if not depth and not (whole_author or local_media_kinds):
            episode = _episode_inventory(unit, entries, device, protected_roots, check_cancelled)
            if episode is not None:
                items, episode_dirs = episode
                if directories is not None:
                    directories.update(episode_dirs)
                yield from items
                return
            owned_sources = _semantic_branch_sources(unit, entries, device, protected_roots)
            if owned_sources is None:
                repeated = _repeated_work_wrapper(unit, entries, device, protected_roots)
        work_component = (_work_media_component(unit, entries, device, protected_roots)
                          if not depth and not (whole_author or local_media_kinds or owned_sources) else None)
        range_starts = owned_sources.photo_range_starts if owned_sources else None
        range_start = range_starts.get(folder.name) if range_starts and depth == 1 else None
        for name, info in entries:
            path = folder / name
            if name.casefold().startswith(".nfc-"):
                raise ValueError(f"Reserved workspace needs reconciliation: {path}")
            if whole_author and _protected(path, protected_roots):
                raise ValueError(f"Protected entry in author directory: {path}")
            if stat.S_ISDIR(info.st_mode):
                if whole_author:
                    if info.st_dev != device:
                        raise ValueError(f"Cross-device directory in author tree: {path}")
                    children.append((path, depth + 1))
                    continue
                if depth and local_media_kinds:
                    raise ValueError("A local media bucket now contains a nested directory")
                if _protected(path, protected_roots):
                    if depth:
                        raise ValueError("Classification wrapper contains a protected directory")
                elif not depth and local_media_kinds:
                    if ((local_scope == DIRECT_MEDIA_SCOPE and name in local_children)
                            or (local_scope is None and _labelled_bucket_kind(name) in local_media_kinds
                                and _verified_bucket_kind(path, device))):
                        children.append((path, depth + 1))
                elif (not depth and owned_sources is not None and name in owned_sources.wrappers
                      or (repeated is not None and repeated.is_relative_to(path)) or name == work_component):
                    children.append((path, depth + 1))
                elif _is_wrapper(folder, name, device=device, protected_roots=protected_roots):
                    if depth or _pure_wrapper(path, device, protected_roots):
                        children.append((path, depth + 1))
                elif depth:
                    raise ValueError("Classification wrapper may contain independent works")
                continue
            if not stat.S_ISREG(info.st_mode) or info.st_dev != device:
                raise ValueError(f"Unsupported or cross-device entry: {path}")
            kind = _classify(name)
            if not depth and local_scope == DIRECT_MEDIA_SCOPE and kind == "Other":
                continue
            if owned_sources is not None:
                owned_totals[kind] += 1
            if depth and local_media_kinds:
                branch_kind = (local_children.get(folder.name) if local_scope == DIRECT_MEDIA_SCOPE
                               else _labelled_bucket_kind(folder.name))
                if kind != branch_kind:
                    raise ValueError("A local media bucket changed its file type")
            files += 1
            if files > MAX_PACKAGE_FILES:
                raise ValueError("Media unit file limit exceeded")
            yield {
                "path": str(path), "name": name, "kind": kind,
                "bytes": int(info.st_size), "dev": int(info.st_dev),
                "ino": int(info.st_ino), "mtime_ns": int(info.st_mtime_ns),
                **({"photo_range_start": range_start} if range_start is not None else {}),
            }
        folders.extend(reversed(children))
    if owned_sources is not None and owned_totals != owned_sources.totals:
        raise ValueError(f"Work media count changed during inventory: {unit}")


def walk_organizing_unit(
    unit: Path, *, mode: str, media_package_root: Path | None = None,
    quarantine_root: Path | None = None, directories: set[Path] | None = None,
    local_media_kinds: tuple[str, ...] = (), whole_author: bool = False,
    local_scope: str | None = None,
    check_cancelled: Callable[[], None] | None = None,
) -> Iterator[dict]:
    """Return the raw inventory required to revalidate a previously checked unit."""
    unit = Path(unit)
    if whole_author and (mode not in {"semantic", "luolcy"} or local_media_kinds):
        raise ValueError("Invalid whole-author media scope")
    if local_media_kinds and (mode != "semantic" or not {"P", "V"}.intersection(local_media_kinds)
                              or any(kind not in ("P", "V", "Other") for kind in local_media_kinds)):
        raise ValueError("Invalid local media scope")
    if local_scope is not None and (
        local_scope != DIRECT_MEDIA_SCOPE or mode != "semantic" or whole_author
        or not local_media_kinds or set(local_media_kinds) - {"P", "V"}
    ):
        raise ValueError("Invalid direct media scope")
    if mode == "luolcy" and media_package_root is not None:
        if whole_author:
            items, _, _ = _luolcy_author_inventory(unit, media_package_root, check_cancelled=check_cancelled)
            if directories is not None:
                directories.add(unit)
            yield from items
        else:
            yield from _walk_package(unit, directories=directories)
    elif mode == "semantic":
        protected_roots = _resolved_protected_roots(media_package_root, quarantine_root)
        yield from _semantic_inventory(
            unit, protected_roots, directories, local_media_kinds, whole_author=whole_author,
            local_scope=local_scope, check_cancelled=check_cancelled,
        )
    else:
        raise ValueError("Invalid organizer mode or missing MediaPackage root")


def _blocked(unit: Path, mode: str, reason: str) -> dict:
    return {
        "unit": str(unit), "package": str(unit), "organizer_mode": mode,
        "status": "blocked", "reason": reason, "conflicts": [{"reason": reason}],
        "total_files": 0, "totals": {"P": 0, "V": 0, "Other": 0}, "total_bytes": 0,
        "groups": [], "sample_moves": [], "total_proposals": 0, "actual_moves": 0,
        "needed_moves": 0, "renamed_count": 0, "wrapper_cleanup": [], "read_only": True,
    }


def _held_files(unit: Path, entries: list[tuple[str, os.stat_result]], reason: str) -> dict:
    """Report the local unassigned files while leaving descendants to discovery."""
    record = _blocked(unit, "semantic", reason)
    for name, info in entries:
        if stat.S_ISREG(info.st_mode) and not is_reserved_workspace(unit / name):
            record["totals"][_classify(name)] += 1
            record["total_files"] += 1
            record["total_bytes"] += info.st_size
    return record


def _author_loose_record(unit: Path, items: list[dict], included: set[Path],
                         protected_roots: tuple[Path, ...]) -> dict | None:
    """Recheck ownership of author-level loose files before freezing a changing layout."""
    if not _author_layer(unit) or not any(Path(row["path"]).parent == unit for row in items):
        return None
    device = items[0]["dev"]
    entries = _entries(unit, device)
    for name, info in entries:
        child = unit / name
        if (stat.S_ISDIR(info.st_mode) and info.st_dev == device
                and child not in included and not _protected(child, protected_roots)):
            return _held_files(unit, entries, "作者层散文件待确认")
    return None


def _regular_media_entries(path: Path, device: int) -> list[tuple[str, os.stat_result]]:
    """Read a leaf without admitting symbolic links, mount aliases, or nested directories."""
    try:
        entries = _entries(path, device)
    except (OSError, ValueError):
        return []
    if not all(
        stat.S_ISREG(info.st_mode) and info.st_dev == device and not name.casefold().startswith(".nfc-")
        for name, info in entries
    ):
        return []
    return entries


def _episode_key(name: str) -> tuple[str, str] | None:
    """Recognize the title and ordinal of an independent named episode."""
    match = _EPISODE_TITLE.fullmatch(normalize("NFKC", name))
    if match is None:
        return None
    return (match["series"] or "").strip().casefold(), match["ordinal"].lstrip("0") or "0"


def _episode_has_peer(unit: Path, key: tuple[str, str], device: int,
                      protected_roots: tuple[Path, ...]) -> bool:
    """Require a numbered peer from the same series before using the full episode root."""
    try:
        siblings = _entries(unit.parent, device)
    except (OSError, ValueError):
        return False
    series, ordinal = key
    return any(
        name != unit.name and info.st_dev == device and stat.S_ISDIR(info.st_mode)
        and not _protected(unit.parent / name, protected_roots)
        and (peer := _episode_key(name)) is not None and peer[0] == series
        and peer[1].isdigit() and peer[1] != ordinal
        for name, info in siblings
    )


def _keeps_episode_boundary(name: str) -> bool:
    """Identify nested collections, versions and installments with their own scope."""
    label = normalize("NFKC", name)
    return bool(
        _EPISODE_BOUNDARY.search(label) or _episode_key(label) or _NUMBERED_LEAF.fullmatch(label)
        or _append_calendar_boundary(label) or _COLLECTION_CONTEXT.search(label) or _WORK_SEQUENCE_LABEL.search(label)
        or _WORK_VARIANT_LABEL.search(label) or label.casefold() in _VERSION_NAMES | _EPISODE_ARCHIVES
    )


def _episode_inventory(
    unit: Path, entries: _DirectoryEntries, device: int, protected_roots: tuple[Path, ...],
    check_cancelled: Callable[[], None] | None,
) -> tuple[list[dict], set[Path]] | None:
    """Collect an episode with download metadata or photo supplements inside its own boundary."""
    key = _episode_key(unit.name)
    if (key is None or not any(stat.S_ISDIR(info.st_mode) for _, info in entries)
            or not _episode_has_peer(unit, key, device, protected_roots)):
        return None
    items: list[dict] = []
    directories: set[Path] = set()
    pending = [(unit, 0, False)]
    matches_download = False
    direct_video = False
    nested_kinds: set[str] = set()
    try:
        while pending:
            if check_cancelled is not None:
                check_cancelled()
            folder, depth, in_cache = pending.pop()
            if depth > MAX_DEPTH or len(directories) >= MAX_PACKAGE_DIRECTORIES:
                return None
            directories.add(folder)
            for name, info in entries if depth == 0 else _entries(folder, device):
                path = folder / name
                if (info.st_dev != device or name.casefold().startswith(".nfc-")
                        or _protected(path, protected_roots)):
                    return None
                if stat.S_ISDIR(info.st_mode):
                    cache = in_cache or name.casefold() == "@eadir"
                    if not cache and _keeps_episode_boundary(name):
                        return None
                    pending.append((path, depth + 1, cache))
                    continue
                if not stat.S_ISREG(info.st_mode) or len(items) >= MAX_PACKAGE_FILES:
                    return None
                kind = _classify(name)
                if kind == "Other" and not in_cache:
                    return None
                if depth:
                    nested_kinds.add(kind)
                else:
                    direct_video |= kind == "V"
                matches_download |= in_cache
                items.append(_author_media_row(path, info, kind))
    except (OSError, ValueError):
        return None
    if (matches_download and any(row["kind"] in {"P", "V"} for row in items)
            or direct_video and nested_kinds == {"P"}):
        return items, directories
    return None


def _numbered_media_leaf(folder: Path, files: _DirectoryEntries, kind: str, device: int,
                         protected_roots: tuple[Path, ...]) -> bool:
    """Verify the existing one-based sequence before preserving its numbers."""
    return bool(files) and all(
        stat.S_ISREG(info.st_mode) and info.st_dev == device and not _protected(folder / name, protected_roots)
        and _classify(name) == kind and name == numbered_name(index, name)
        for index, (name, info) in enumerate(files, 1)
    )


def _video_wrapper_append_source(unit: Path, entries: _DirectoryEntries, children: list[str], device: int,
                                 protected_roots: tuple[Path, ...]) -> str | None:
    """Recognize one redundant video label beside the numbered files of V."""
    candidates = [name for name in children if name.casefold() in _VIDEO_WRAPPER_ALIASES]
    if (unit.name.casefold() != "v" or len(candidates) != 1
            or any(name != candidates[0] and _is_wrapper(unit, name, device=device, protected_roots=protected_roots)
                   for name in children)):
        return None
    name, = candidates
    branch = unit / name
    if _protected(branch, protected_roots):
        return None
    outer = [(name, info) for name, info in entries if stat.S_ISREG(info.st_mode)]
    files = _regular_media_entries(branch, device)
    if (len(outer) + len(files) > MAX_FILES_PER_GROUP
            or not _numbered_media_leaf(unit, outer, "V", device, protected_roots)
            or not _numbered_media_leaf(branch, files, "V", device, protected_roots)):
        return None
    return name


def _direct_leaf_kinds(path: Path, device: int) -> set[str]:
    """Return media kinds only for a folder containing regular files directly."""
    return {_classify(filename) for filename, _ in _regular_media_entries(path, device)}


def _work_media_counts(
    folder: Path, entries: list[tuple[str, os.stat_result]], device: int, protected_roots: tuple[Path, ...], *,
    exclude: str | None = None, allow_buckets: bool = False,
) -> Counter[str] | None:
    """Count direct media and, when allowed, verified P/V output buckets."""
    counts: Counter[str] = Counter()
    for name, info in entries:
        path = folder / name
        if (info.st_dev != device or _protected(path, protected_roots)
                or name.casefold().startswith(".nfc-")):
            return None
        if name == exclude:
            continue
        if stat.S_ISREG(info.st_mode):
            kind = _classify(name)
            if kind not in {"P", "V"}:
                return None
            counts[kind] += 1
        elif allow_buckets and stat.S_ISDIR(info.st_mode):
            bucket = MEDIA_BUCKET_PATTERN.fullmatch(name)
            if bucket is None:
                return None
            kind = bucket["kind"].upper()
            files = _regular_media_entries(path, device)
            if not files or any(_classify(filename) != kind or _protected(path / filename, protected_roots)
                                for filename, _ in files):
                return None
            size = sum(file_info.st_size for _, file_info in files)
            if bucket["label"] != f"[{len(files)} {_size_label(size)}]":
                return None
            counts[kind] += len(files)
        else:
            return None
    return counts


def _normalized_work_title(title: str) -> str:
    """Compare titles across punctuation and spacing while keeping letters and digits."""
    return "".join(char for char in normalize("NFKC", title).casefold() if char.isalnum())


def _has_work_edition(title: str) -> bool:
    """Preserve named variants while allowing resolution within a shared work title."""
    # The version pattern includes its leading separator when matching an alphanumeric label.
    return any(not (_RESOLUTION_NAME.fullmatch(match[0]) or _RESOLUTION_NAME.fullmatch(match[0][1:]))
               for match in _WORK_VARIANT_LABEL.finditer(title))


def _photo_range_starts(
    unit: Path, branches: list[str], title: str, expected: Counter[str], device: int,
    protected_roots: tuple[Path, ...],
) -> dict[str, int] | None:
    """Require consecutive labelled photo ranges and one matching video branch."""
    ranges: list[tuple[int, int, str]] = []
    video_parts = 0
    matching_title = None
    for name in branches:
        photo = _WORK_PHOTO_RANGE.fullmatch(name)
        media = photo or _WORK_VIDEO_PART.fullmatch(name)
        if media is None or _has_work_edition(media["title"]):
            return None
        stem = _normalized_work_title(media["title"])
        if len(stem) < 3 or stem not in title or (matching_title is not None and matching_title != stem):
            return None
        matching_title = stem
        branch = unit / name
        files = _regular_media_entries(branch, device)
        counts = _work_media_counts(branch, files, device, protected_roots)
        if photo:
            first, last = int(photo["first"]), int(photo["last"])
            if last < first or counts != Counter(P=last - first + 1):
                return None
            ranges.append((first, last, name))
        elif counts == Counter(V=expected["V"]):
            video_parts += 1
        else:
            return None
    ranges.sort()
    if (video_parts != 1 or len(ranges) < 2 or ranges[0][0] != 1 or ranges[-1][1] != expected["P"]
            or any(previous[1] + 1 != following[0] for previous, following in zip(ranges, ranges[1:]))):
        return None
    return {name: first for first, _, name in ranges}


def _r16_jpeg_work_part(
    unit: Path, name: str, entries: _DirectoryEntries, expected: Counter[str], device: int,
    protected_roots: tuple[Path, ...],
) -> bool:
    """Recognize an exact R16-JPEG label only beside the same numbered work's videos."""
    label = _WORK_R16_JPEG.fullmatch(name)
    if (label is None or expected["V"] != 1 or len(entries) != 2
            or not re.match(re.escape(label["stem"]) + r"(?![a-z0-9])", unit.name, re.I)):
        return False
    video, = (filename for filename, _ in entries if filename != name)
    if (_has_work_edition(Path(video).stem)
            or _work_media_counts(unit, entries, device, protected_roots, exclude=name) != Counter(V=1)):
        return False
    folder = unit / name
    files = _regular_media_entries(folder, device)
    return (len(files) == expected["P"]
            and all(Path(filename).suffix.casefold() in _JPEG_EXTENSIONS for filename, _ in files)
            and _work_media_counts(folder, files, device, protected_roots) == Counter(P=expected["P"]))


def _split_work_sources(
    unit: Path, entries: _DirectoryEntries, device: int, protected_roots: tuple[Path, ...],
) -> _OwnedMediaSources | None:
    """Verify declared identity, media roles and counts before claiming work branches."""
    if len(entries) < 2 or ("[" not in unit.name and "【" not in unit.name) or _author_layer(unit):
        return None
    label = _declared_media_count_label(unit)
    totals = _SPLIT_WORK_TOTAL.fullmatch(label) if label is not None else None
    if totals is None or _append_calendar_boundary(unit.name) or _is_wrapper(unit.parent, unit.name):
        return None
    title = _BRACKETED_LABEL.sub(lambda match: "" if match[1] == label else match[0], unit.name)
    if _has_work_edition(title):
        return None
    expected = Counter(P=int(totals[1]), V=int(totals[2]))
    if not all(expected.values()) or expected.total() > MAX_PACKAGE_FILES:
        return None
    if any(info.st_dev != device or _protected(unit / name, protected_roots)
           or is_reserved_workspace(unit / name) for name, info in entries):
        return None
    branches = [name for name, info in entries if stat.S_ISDIR(info.st_mode)]
    if len(branches) == 1 and _r16_jpeg_work_part(unit, branches[0], entries, expected, device, protected_roots):
        return _OwnedMediaSources(set(branches), expected)
    if len(branches) >= 3 and len(branches) == len(entries):
        starts = _photo_range_starts(unit, branches, _normalized_work_title(title), expected, device, protected_roots)
        if starts is not None:
            return _OwnedMediaSources(set(branches), expected, starts)
    return None


def _one_level_work_shell(
    unit: Path, entries: _DirectoryEntries, device: int, protected_roots: tuple[Path, ...],
) -> _OwnedMediaSources | None:
    """Remove a sole numbered photo layer or a sole proven same-issue video layer."""
    branches = [name for name, info in entries if stat.S_ISDIR(info.st_mode)]
    if len(branches) != 1:
        return None
    name = branches[0]
    folder = unit / name
    if _protected(folder, protected_roots):
        return None
    if len(entries) == 1 and _NUMBERED_WORK_CODE.fullmatch(unit.name) and _PICTURE_SERIES_LABEL.fullmatch(name):
        files = _regular_media_entries(folder, device)
        counts = _work_media_counts(folder, files, device, protected_roots)
        if counts and set(counts) == {"P"} and counts["P"] <= MAX_FILES_PER_GROUP:
            return _OwnedMediaSources({name}, counts)
    issue = _SAME_ISSUE_TITLE.fullmatch(unit.name)
    if len(entries) != 2 or issue is None or issue[1] != name:
        return None
    direct = _work_media_counts(unit, entries, device, protected_roots, exclude=name)
    if direct != Counter(V=1):
        return None
    files = _regular_media_entries(folder, device)
    counts = _work_media_counts(folder, files, device, protected_roots)
    if not counts or set(counts) != {"V"} or counts["V"] + 1 > MAX_FILES_PER_GROUP:
        return None
    issue_mark = re.compile(r"(?<![0-9])" + re.escape(name) + r"(?![0-9])")
    stems = [Path(filename).stem for filename, _ in files + entries if filename != name]
    if any(not issue_mark.search(stem) or _has_work_edition(stem)
           or re.search(r"未删减|剪辑", stem) for stem in stems):
        return None
    return _OwnedMediaSources({name}, counts + direct)


def _dated_export_sources(
    unit: Path, label: re.Match[str], entries: _DirectoryEntries, device: int,
    protected_roots: tuple[Path, ...],
) -> _OwnedMediaSources | None:
    """Treat numbered video exports as parts only when names and declared counts agree."""
    names = {name for name, info in entries if stat.S_ISDIR(info.st_mode)
             and info.st_dev == device and not _protected(unit / name, protected_roots)}
    if len(names) != len(entries) or len(names) < 3 or "P" not in names:
        return None
    if names - {"P"} != {str(index) for index in range(1, len(names))}:
        return None
    totals: Counter[str] = Counter()
    export_names = set()
    for name in names:
        folder = unit / name
        files = _regular_media_entries(folder, device)
        counts = _work_media_counts(folder, files, device, protected_roots)
        kind = "P" if name == "P" else "V"
        if not counts or set(counts) != {kind}:
            return None
        for filename, _ in files:
            stem = re.sub(r"\s*\([0-9]+\)$", "", Path(filename).stem).strip().casefold()
            if not stem or _has_work_edition(stem):
                return None
            export_names.add(stem)
        totals.update(counts)
    if len(export_names) == 1 and totals == Counter(V=int(label[1]), P=int(label[2])):
        return _OwnedMediaSources(names, totals)
    return None


def _dated_alias_sources(
    unit: Path, label: re.Match[str], entries: _DirectoryEntries, device: int,
    protected_roots: tuple[Path, ...],
) -> _OwnedMediaSources | None:
    """Remove an alias layer only when existing nested media classification proves a depth saving."""
    if len(entries) != 1:
        return None
    name, info = entries[0]
    folder = unit / name
    if (not stat.S_ISDIR(info.st_mode) or info.st_dev != device or _protected(folder, protected_roots)
            or _has_work_edition(name) or _append_calendar_boundary(name)):
        return None
    title = label["title"].strip()
    alias_title = re.sub(r"^\[[^\[\]]+\]\s*", "", name)
    same_title = len(title) >= 2 and _normalized_work_title(alias_title) == _normalized_work_title(title)
    same_date = re.fullmatch(r"[^\W\d_]{1,12}\s*" + re.escape(label["date"]), name) is not None
    label_counts = _SPLIT_WORK_TOTAL.fullmatch(label["round"] or label["wide"] or label["square"])
    if not label_counts or not (same_title or same_date):
        return None
    expected = Counter(P=int(label_counts[1]), V=int(label_counts[2]))
    if not all(expected.values()):
        return None
    try:
        inner = _entries(folder, device)
    except (OSError, ValueError):
        return None
    branches = [(child, st) for child, st in inner if stat.S_ISDIR(st.st_mode)]
    if not branches:
        return None
    totals = _work_media_counts(folder, [(child, st) for child, st in inner if not stat.S_ISDIR(st.st_mode)],
                               device, protected_roots)
    if totals is None:
        return None
    for child, st in branches:
        media = folder / child
        if st.st_dev != device or _protected(media, protected_roots):
            return None
        if child.casefold() in _PHOTO_ALIASES | {"p", "图包"}:
            kind = "P"
        elif child.casefold() in {"v", "视频", "video", "videos"}:
            kind = "V"
        else:
            return None
        files = _regular_media_entries(media, device)
        counts = _work_media_counts(media, files, device, protected_roots)
        if not counts or set(counts) != {kind} or not _is_wrapper(
            folder, child, device=device, protected_roots=protected_roots,
        ):
            return None
        totals.update(counts)
    return _OwnedMediaSources({name}, totals) if totals == expected else None


def _same_published_work_title(unit: Path, alias: str, title: str) -> bool:
    """Accept an exact title, optionally preceded by a credit or the owning author's alias."""
    without_credit = re.sub(r"^\[[^\[\]]+\]\s*", "", alias)
    wanted = _normalized_work_title(title)
    if len(wanted) < 3:
        return False
    if _normalized_work_title(without_credit) == wanted:
        return True
    prefix, separator, tail = without_credit.partition("-")
    if not separator or _normalized_work_title(tail) != wanted:
        return False
    return _matches_published_author_credit(unit, prefix)


def _matches_published_author_credit(unit: Path, credit: str, *, allow_prefix: bool = False) -> bool:
    """Match a declared author name or an unambiguous Chinese alias abbreviation."""
    author = next((parent for parent in unit.parents if _calendar_author_layer(parent)), None)
    if author is None:
        return False
    wanted = _normalized_work_title(credit)
    if wanted in {
        _normalized_work_title(name) for name in re.split(r"[()（）]", author.name) if name.strip()
    }:
        return True
    if (not allow_prefix or len(wanted) < 2
            or not all(unicode_name(char, "").startswith("CJK UNIFIED IDEOGRAPH-") for char in wanted)):
        return False
    aliases = {_normalized_work_title(name) for name in re.findall(r"\(([^()]+)\)", normalize("NFKC", author.name))}
    return sum(alias.startswith(wanted) for alias in aliases) == 1


def _same_published_work_month_day(unit: Path, alias: str, stamp: str, device: int) -> bool:
    """Resolve a short date against its archive month, author and unique release date."""
    short = _PUBLISHED_MONTH_DAY_ALIAS.fullmatch(alias)
    archive = _PUBLISHED_ARCHIVE_MONTH.fullmatch(unit.parent.name)
    if (short is None or archive is None or short["stamp"] != stamp[3:]
            or archive["month"][2:] != stamp[:5]
            or not _matches_published_author_credit(unit, short["credit"], allow_prefix=True)):
        return False
    try:
        release = date.fromisoformat((archive["month"][:2] + stamp).replace(".", "-"))
        siblings = _entries(unit.parent, device)
    except (OSError, ValueError):
        return False
    # The missing year is resolved only within one archive. Any second release
    # with the same complete date keeps the short alias independent.
    month = f"0?{release.month}" if release.month < 10 else str(release.month)
    day = f"0?{release.day}" if release.day < 10 else str(release.day)
    peer_date = re.compile(
        rf"\s*[【\[(（]?(?:{release.year}|{stamp[:2]})"
        rf"(?:[._-]{month}[._-]{day}|{release:%m%d}|年{month}月{day}日)(?![0-9])"
    )
    return not any(name != unit.name and peer_date.match(name) for name, _ in siblings)


def _published_alias_expected(unit: Path, alias: str, stamp: str, device: int) -> Counter[str] | None:
    """Read a single P/V declaration and verify the alias's title or date."""
    dated_name = unit.name[len(stamp):]
    matches = list(_PUBLISHED_WORK_COUNTS.finditer(dated_name))
    if len(matches) != 1:
        return None
    counts = matches[0]
    prefix = dated_name[:counts.start()].strip()
    title = prefix.rstrip("([【").rstrip()
    tail = dated_name[counts.end():].strip()
    same_date = re.fullmatch(r"[^\W\d_]{1,12}\s*" + re.escape(stamp), alias) is not None
    close = _WORK_COUNT_BRACKETS.get(prefix[-1:]) if title != prefix else None
    if close is not None:
        if tail.startswith(close):
            tail = tail[1:].strip()
        elif tail or not same_date:
            # A truncated declaration is acceptable only with an independently matching full date.
            return None
    if (not title or not _PUBLISHED_WORK_TRAILER.fullmatch(tail)
            or not (same_date or _same_published_work_title(unit, alias, title)
                    or _same_published_work_month_day(unit, alias, stamp, device))):
        return None
    totals = Counter(P=int(counts[1]), V=int(counts[2]))
    return totals if all(0 < total <= MAX_FILES_PER_GROUP for total in totals.values()) else None


def _numbered_pv_bucket_counts(folder: Path, device: int, protected_roots: tuple[Path, ...]) -> Counter[str] | None:
    """Verify the size, count and numbering of exactly one P and one V bucket."""
    try:
        buckets = _entries(folder, device)
    except (OSError, ValueError):
        return None
    if len(buckets) != 2:
        return None
    totals: Counter[str] = Counter()
    for name, info in buckets:
        path = folder / name
        if not stat.S_ISDIR(info.st_mode) or info.st_dev != device or _protected(path, protected_roots):
            return None
        kind = name[:1]
        if kind not in {"P", "V"} or kind in totals:
            return None
        files = _regular_media_entries(path, device)
        size = sum(info.st_size for _, info in files)
        if (len(files) > MAX_FILES_PER_GROUP or name != f"{kind} [{len(files)} {_size_label(size)}]"
                or not _numbered_media_leaf(path, files, kind, device, protected_roots)):
            return None
        totals[kind] = len(files)
    return totals


def _published_alias_sources(
    unit: Path, entries: _DirectoryEntries, device: int, protected_roots: tuple[Path, ...],
) -> _OwnedMediaSources | None:
    """Lift the exact numbered P and V buckets of one proven alias to the work root."""
    stamp = _PUBLISHED_WORK_DATE.match(unit.name)
    if stamp is None or len(entries) != 1:
        return None
    alias, info = entries[0]
    folder = unit / alias
    if (not stat.S_ISDIR(info.st_mode) or info.st_dev != device or _protected(folder, protected_roots)
            or is_reserved_workspace(folder) or _append_calendar_boundary(alias)
            or alias.casefold() in _VERSION_NAMES or _WORK_VARIANT_LABEL.search(alias)):
        return None
    expected = _published_alias_expected(unit, alias, stamp[0], device)
    if expected is None:
        return None
    totals = _numbered_pv_bucket_counts(folder, device, protected_roots)
    return _OwnedMediaSources({alias}, expected) if totals == expected else None


def _same_export_date(work: re.Match[str], wrapper: re.Match[str]) -> bool:
    """Validate the export date and resolve a two-digit work year from it."""
    try:
        stamp = date(int(wrapper["year"]), int(wrapper["month"]), int(wrapper["day"]))
    except ValueError:
        return False
    year = stamp.year % 100 if len(work["year"]) == 2 else stamp.year
    return (year, stamp.month, stamp.day) == tuple(int(work[key]) for key in ("year", "month", "day"))


def _export_title_matches_media(title: str, totals: Counter[str], *, require_counts: bool) -> bool:
    """Verify any media declaration and require a title separate from the counts."""
    matches = list(_PUBLISHED_WORK_COUNTS.finditer(title))
    if not matches:
        return (not require_counts and not _ADDITIONAL_WORK_COUNT.search(title)
                and any(char.isalpha() for char in title))
    if len(matches) != 1:
        return False
    counts, = matches
    name, trail = title[:counts.start()], title[counts.end():]
    return (any(char.isalpha() for char in name)
            and not any(_ADDITIONAL_WORK_COUNT.search(part) for part in (name, trail))
            and totals == Counter(P=int(counts[1]), V=int(counts[2])))


def _work_export_sources(unit: Path, entries: _DirectoryEntries, device: int,
                         protected_roots: tuple[Path, ...]) -> _OwnedMediaSources | None:
    """Combine one generated export wrapper with the files already in its work root."""
    if len(entries) < 2 or _author_layer(unit):
        return None
    directories = [(name, info) for name, info in entries if stat.S_ISDIR(info.st_mode)]
    if len(directories) != 1:
        return None
    (name, info), = directories
    dated = _DATED_EXPORT_WRAPPER.fullmatch(name)
    paged = _PAGED_EXPORT_WRAPPER.fullmatch(name)
    if dated is None and paged is None:
        return None
    folder = unit / name
    if (info.st_dev != device or _protected(folder, protected_roots) or _has_work_edition(unit.name)
            or _append_calendar_boundary(unit.name) or _is_wrapper(unit.parent, unit.name)
            or _fantia_collection(unit)):
        return None
    title = unit.name
    if dated is not None:
        stamp = _EXPORT_WORK_DATE.match(title)
        if stamp is None or not _same_export_date(stamp, dated):
            return None
        title = title[stamp.end():]
    elif (_COLLECTION_CONTEXT.search(title) or _PAGED_EXPORT_WRAPPER.fullmatch(title)
          or _DATED_EXPORT_WRAPPER.fullmatch(title) or int(paged["first"]) > int(paged["last"] or paged["first"])):
        return None

    direct = [(entry, st) for entry, st in entries if entry != name]
    kinds = {_classify(entry) for entry, _ in direct}
    if kinds not in ({"P"}, {"V"}):
        return None
    kind, = kinds
    if not _numbered_media_leaf(unit, direct, kind, device, protected_roots):
        return None
    totals = _numbered_pv_bucket_counts(folder, device, protected_roots)
    if totals is None:
        return None
    totals[kind] += len(direct)
    if (totals[kind] > MAX_FILES_PER_GROUP
            or not _export_title_matches_media(title, totals, require_counts=dated is not None)):
        return None
    return _OwnedMediaSources({name}, totals)


def _dated_default_photo_sources(unit: Path, entries: _DirectoryEntries, device: int,
                                 protected_roots: tuple[Path, ...]) -> _OwnedMediaSources | None:
    """Join a default photo leaf to the numbered photos of a clearly named work."""
    date = _PUBLISHED_WORK_DATE.match(unit.name)
    if date is None or _author_layer(unit):
        return None
    title = unit.name[date.end():].strip()
    if len(_normalized_work_title(title)) < 2 or _has_work_edition(title) or _COLLECTION_CONTEXT.search(title):
        return None
    directories = [(name, info) for name, info in entries if stat.S_ISDIR(info.st_mode)]
    if len(directories) != 1:
        return None
    (name, info), = directories
    branch = unit / name
    if not _DEFAULT_FOLDER.fullmatch(name) or info.st_dev != device or _protected(branch, protected_roots):
        return None
    outer = [(entry, info) for entry, info in entries if entry != name]
    files = _regular_media_entries(branch, device)
    count = len(outer) + len(files)
    if (count > MAX_FILES_PER_GROUP or not _numbered_media_leaf(unit, outer, "P", device, protected_roots)
            or not _numbered_media_leaf(branch, files, "P", device, protected_roots)):
        return None
    return _OwnedMediaSources({name}, Counter(P=count))


def _titled_photo_bucket_sources(unit: Path, entries: _DirectoryEntries, device: int,
                                 protected_roots: tuple[Path, ...]) -> _OwnedMediaSources | None:
    """Lift intact, consecutive picture buckets paired with the work's direct videos."""
    work = _NUMBERED_TITLED_WORK.fullmatch(unit.name)
    if work is None or _author_layer(unit) or _has_work_edition(work["title"]):
        return None
    name = next((name for name, info in entries if stat.S_ISDIR(info.st_mode)
                 and normalize("NFC", name).casefold() == normalize("NFC", work["title"] + "图").casefold()), None)
    if name is None or _protected(unit / name, protected_roots):
        return None
    videos = [(entry, info) for entry, info in entries if entry != name]
    if (len(videos) > MAX_FILES_PER_GROUP
            or not _numbered_media_leaf(unit, videos, "V", device, protected_roots)):
        return None
    branch = unit / name
    try:
        buckets = _entries(branch, device)
    except (OSError, ValueError):
        return None
    if len(buckets) < 2:
        return None
    counts = {}
    for bucket, info in buckets:
        label = MEDIA_BUCKET_PATTERN.fullmatch(bucket)
        folder = branch / bucket
        if (label is None or label["kind"] != "P" or not stat.S_ISDIR(info.st_mode)
                or info.st_dev != device or _protected(folder, protected_roots)):
            return None
        index = int(label["index"] or "0")
        if index >= len(buckets) or index in counts:
            return None
        files = _regular_media_entries(folder, device)
        size = sum(file_info.st_size for _, file_info in files)
        if (len(files) > MAX_FILES_PER_GROUP or (index < len(buckets) - 1 and len(files) != MAX_FILES_PER_GROUP)
                or label["label"] != f"[{len(files)} {_size_label(size)}]"
                or not _numbered_media_leaf(folder, files, "P", device, protected_roots)):
            return None
        counts[index] = len(files)
    return _OwnedMediaSources({name}, Counter(P=sum(counts.values()), V=len(videos)))


def _legacy_counted_bucket_sources(unit: Path, entries: _DirectoryEntries, device: int,
                                   protected_roots: tuple[Path, ...]) -> _OwnedMediaSources | None:
    """Recognize an intact pair of old Pic/Video buckets belonging to one work."""
    if len(entries) != 2 or _author_layer(unit):
        return None
    label = _declared_media_count_label(unit)
    declared = _SPLIT_WORK_TOTAL.fullmatch(label) if label is not None else None
    if declared is None:
        return None
    expected = Counter(P=int(declared[1]), V=int(declared[2]))
    totals: Counter[str] = Counter()
    for name, info in entries:
        bucket = _LEGACY_COUNTED_BUCKET.fullmatch(name)
        folder = unit / name
        if (bucket is None or not stat.S_ISDIR(info.st_mode) or info.st_dev != device
                or _protected(folder, protected_roots)):
            return None
        kind = "P" if bucket["label"].casefold() == "pic" else "V"
        count = int(bucket["count"])
        if kind != bucket["kind"].upper() or kind in totals or count != expected[kind] or count > MAX_FILES_PER_GROUP:
            return None
        files = _regular_media_entries(folder, device)
        if len(files) != count or not _numbered_media_leaf(folder, files, kind, device, protected_roots):
            return None
        totals[kind] = count
    # Let the standard planner label output sizes from actual bytes.
    return _OwnedMediaSources({name for name, _ in entries}, totals)


def _counted_photo_supplements(unit: Path, entries: _DirectoryEntries, device: int,
                               protected_roots: tuple[Path, ...]) -> _OwnedMediaSources | None:
    """Collect supplemental photos or one mixed unlock when the work totals prove ownership."""
    branches = {name: info for name, info in entries if stat.S_ISDIR(info.st_mode)
                and normalize("NFKC", name).strip() in _COUNTED_PHOTO_SUPPLEMENTS}
    if (not branches or _author_layer(unit) or _is_wrapper(unit.parent, unit.name)
            or _fantia_collection(unit) or _fantia_collection(unit.parent)):
        return None
    label = _declared_media_count_label(unit)
    if label is None or not any(char.isalpha() for char in _BRACKETED_LABEL.sub("", unit.name)):
        return None
    photos = _PHOTO_PACK_TOTAL.fullmatch(label)
    mixed = _SPLIT_WORK_TOTAL.fullmatch(label)
    if photos is None and mixed is None:
        return None
    expected = Counter(P=int(photos[1])) if photos is not None else Counter(P=int(mixed[1]), V=int(mixed[2]))

    primary = [(name, info) for name, info in entries if name not in branches]
    totals = _work_media_counts(unit, primary, device, protected_roots, allow_buckets=True)
    if not totals:
        return None
    for name, info in branches.items():
        folder = unit / name
        if info.st_dev != device or _protected(folder, protected_roots):
            return None
        try:
            children = _entries(folder, device)
        except (OSError, ValueError):
            return None
        counts = _work_media_counts(folder, children, device, protected_roots, allow_buckets=True)
        if not counts:
            return None
        if "V" in counts and (mixed is None or len(branches) != 1 or "P" not in counts
                              or normalize("NFKC", name).strip() not in _PRIVATE_UNLOCK_SUPPLEMENTS):
            return None
        totals.update(counts)
    return _OwnedMediaSources(set(branches), totals) if totals == expected else None


def _single_numbered_work_sources(unit: Path, entries: _DirectoryEntries, device: int,
                                  protected_roots: tuple[Path, ...]) -> _OwnedMediaSources | None:
    """Join a work's direct media with its sole numeric wrapper of numbered P/V buckets."""
    if len(entries) < 2:
        return None
    children = [name for name, info in entries if stat.S_ISDIR(info.st_mode)]
    if (len(children) != 1 or not _NUMBERED_LEAF.fullmatch(children[0]) or _author_layer(unit)
            or _is_wrapper(unit.parent, unit.name) or _FANTIA_POST_COLLECTION.search(unit.parent.name)
            or _fantia_collection(unit)):
        return None
    label = _declared_media_count_label(unit)
    mixed = _SPLIT_WORK_TOTAL.fullmatch(label) if label is not None else None
    if mixed is None or not any(char.isalpha() for char in _BRACKETED_LABEL.sub("", unit.name)):
        return None

    name, = children
    direct = _work_media_counts(unit, entries, device, protected_roots, exclude=name)
    if not direct:
        return None
    nested = _numbered_pv_bucket_counts(unit / name, device, protected_roots)
    expected = Counter(P=int(mixed[1]), V=int(mixed[2]))
    return _OwnedMediaSources({name}, expected) if nested and direct + nested == expected else None


def _semantic_branch_sources(
    unit: Path, entries: _DirectoryEntries, device: int, protected_roots: tuple[Path, ...],
) -> _OwnedMediaSources | None:
    """Use the same proven branch ownership for discovery, preview and execution."""
    owned = (_fantia_post_bucket_sources(unit, entries, device, protected_roots)
             or _split_work_sources(unit, entries, device, protected_roots)
             or _published_alias_sources(unit, entries, device, protected_roots)
             or _dated_default_photo_sources(unit, entries, device, protected_roots)
             or _titled_photo_bucket_sources(unit, entries, device, protected_roots)
             or _legacy_counted_bucket_sources(unit, entries, device, protected_roots)
             or _counted_photo_supplements(unit, entries, device, protected_roots)
             or _single_numbered_work_sources(unit, entries, device, protected_roots)
             or _work_export_sources(unit, entries, device, protected_roots))
    if owned is not None:
        return owned
    if _SAME_ISSUE_TITLE.fullmatch(unit.name) or _NUMBERED_WORK_CODE.fullmatch(unit.name):
        return _one_level_work_shell(unit, entries, device, protected_roots)
    export = _DATED_EXPORT_LABEL.fullmatch(unit.name)
    if export is not None:
        return _dated_export_sources(unit, export, entries, device, protected_roots)
    alias = _DATED_WORK_ALIAS.fullmatch(unit.name)
    if alias is not None:
        return _dated_alias_sources(unit, alias, entries, device, protected_roots)
    return None


def _work_media_component(
    parent: Path, entries: list[tuple[str, os.stat_result]], device: int, protected_roots: tuple[Path, ...],
) -> str | None:
    """Identify one part of a titled work without scanning its siblings repeatedly."""
    totals = _MIXED_WORK_TOTAL.search(parent.name)
    if totals is None or _append_calendar_boundary(parent.name) or _is_wrapper(parent.parent, parent.name):
        return None
    before, after = parent.name[:totals.start()], parent.name[totals.end():]
    if (re.search(r"[0-9]\s*[-－–—~～／]\s*$", before)
            or any(_ADDITIONAL_WORK_COUNT.search(part) for part in (before, after))):
        return None

    candidates = list(islice((
        name for name, info in entries if stat.S_ISDIR(info.st_mode) and not MEDIA_BUCKET_PATTERN.fullmatch(name)
    ), 2))
    if len(candidates) != 1:
        return None
    name, = candidates
    # Fantia post and preview labels carry their own ownership rules.
    if _fantia_post_title(parent) is not None and (
        _fantia_preview_label(name) is not None or _FANTIA_POST_STAMP.fullmatch(name)
        or _FANTIA_NUMBERED_PHOTO_PART.fullmatch(name) or _FANTIA_PHOTO_PART_LABEL.fullmatch(name)
    ):
        return None
    label = name.casefold()
    if (_protected(parent / name, protected_roots) or _is_wrapper(parent, name)
            or label in _TYPED_WRAPPER_KINDS or name == "图包" or _FANTIA_TIER.fullmatch(name)
            or _AMBIGUOUS.fullmatch(name) or _append_calendar_boundary(name)
            or label in _VERSION_NAMES or _WORK_VARIANT_LABEL.search(name)
            or _COLLECTION_CONTEXT.search(name) or _WORK_SEQUENCE_LABEL.search(name)
            or _ADDITIONAL_WORK_COUNT.search(name)):
        return None

    primary = _work_media_counts(parent, entries, device, protected_roots, exclude=name, allow_buckets=True)
    if not primary:
        return None
    try:
        branch = _entries(parent / name, device)
    except (OSError, ValueError):
        return None
    supplemental = _work_media_counts(parent / name, branch, device, protected_roots, allow_buckets=label == "视图")
    if not supplemental:
        return None
    total = primary + supplemental
    if total["P"] != int(totals[1]) or total["V"] != int(totals[2]) or len(total) != 2:
        return None
    if label == "视图":
        return name
    if label == "face":
        return name if primary["P"] > 0 and set(supplemental) == {"P"} else None
    return name if len(primary) == len(supplemental) == 1 else None


def _has_photo_bucket(parent: Path, device: int, protected_roots: tuple[Path, ...]) -> bool:
    """Verify that Selfies has an existing photo bucket in the same work."""
    try:
        siblings = _entries(parent, device)
    except (OSError, ValueError):
        return False
    return any(
        stat.S_ISDIR(info.st_mode)
        and (_labelled_bucket_kind(name) == "P"
             or (_LEGACY_BUCKET.fullmatch(name) and name.casefold().startswith("p")))
        and not _protected(parent / name, protected_roots)
        and _direct_leaf_kinds(parent / name, device) == {"P"}
        for name, info in siblings
    )


def _jpeg_wrapper_contents(folder: Path, device: int, protected_roots: tuple[Path, ...]) -> bool:
    """Verify JPEG files and photo buckets directly inside a JPEG wrapper."""
    if _protected(folder, protected_roots):
        return False
    try:
        entries = _entries(folder, device)
    except (OSError, ValueError):
        return False
    for name, info in entries:
        path = folder / name
        if info.st_dev != device or _protected(path, protected_roots) or is_reserved_workspace(path):
            return False
        if stat.S_ISREG(info.st_mode) and path.suffix.casefold() in _JPEG_EXTENSIONS:
            continue
        bucket = MEDIA_BUCKET_PATTERN.fullmatch(name) if stat.S_ISDIR(info.st_mode) else None
        if bucket is None or bucket["kind"].upper() != "P":
            return False
        files = _regular_media_entries(path, device)
        if not files or any(Path(filename).suffix.casefold() not in _JPEG_EXTENSIONS
                            or _protected(path / filename, protected_roots) for filename, _ in files):
            return False
        size = sum(file_info.st_size for _, file_info in files)
        if bucket["label"] != f"[{len(files)} {_size_label(size)}]":
            return False
    return bool(entries)


def _typed_leaf_wrapper(
    parent: Path, name: str, device: int, protected_roots: tuple[Path, ...],
) -> bool:
    """Confirm a work's direct media label using the leaf's actual files."""
    if (_author_layer(parent) or _CALENDAR_DIRECTORY.fullmatch(parent.name)
            or _is_wrapper(parent.parent, parent.name)):
        return False
    label = name.casefold()
    if label in _JPEG_LABELS:
        # The photo count in a title such as [456P] looks like a resolution label.
        declared_work = (_declared_photo_total(parent) is not None
                         or _MIXED_WORK_TOTAL.search(parent.name) is not None)
        if (_append_calendar_boundary(parent.name) or parent.name.casefold() in _VERSION_NAMES
                or (not declared_work and _WORK_VARIANT_LABEL.search(parent.name))):
            return False
        return _jpeg_wrapper_contents(parent / name, device, protected_roots)
    entries = _regular_media_entries(parent / name, device)
    kind = _TYPED_WRAPPER_KINDS[label]
    if not entries or any(
        _classify(filename) != kind or (label == "gif" and Path(filename).suffix.casefold() != ".gif")
        for filename, _ in entries
    ):
        return False
    return label != "selfies" or _has_photo_bucket(parent, device, protected_roots)


def _fantia_tier_wrapper(post: Path, name: str, device: int, protected_roots: tuple[Path, ...]) -> bool:
    """Recognize a sole tier or an exact same-tier photo and movie pair."""
    if not _fantia_collection(post.parent) or _labelled_bucket_kind(post.name):
        return False
    try:
        fd = _open_directory_nofollow(post)
        try:
            if os.fstat(fd).st_dev != device:
                return False
            with os.scandir(fd) as siblings:
                names = {entry.name for entry in islice(siblings, 3)}
        finally:
            os.close(fd)
    except OSError:
        return False
    if name not in names or any(_protected(post / sibling, protected_roots) for sibling in names):
        return False
    if names == {name}:
        return _direct_leaf_kinds(post / name, device) in ({"P"}, {"V"})
    if len(names) != 2:
        return False
    first, second = sorted(names)
    first_tier = _FANTIA_TIER.fullmatch(first)
    second_tier = _FANTIA_TIER.fullmatch(second)
    if not first_tier or not second_tier or first_tier["amount"] != second_tier["amount"]:
        return False
    # Media type comes from the files. A title or emoji suffix carries no type guarantee.
    kinds = [_direct_leaf_kinds(post / sibling, device) for sibling in (first, second)]
    return {"P"} in kinds and {"V"} in kinds


def _fantia_preview_label(name: str) -> str | None:
    """Recognize a free or cover label, including UTF-8 read as GBK."""
    label = name.casefold()
    if label not in _FANTIA_PREVIEW_NAMES:
        try:
            label = name.encode("gbk").decode("utf-8")
        except UnicodeError:
            return None
    return label if label in _FANTIA_PREVIEW_NAMES else None


def _fantia_photo_parts(names: set[str], title: str) -> bool:
    """Confirm consecutive photo parts or copies of an identically named photo folder."""
    if len(names) < 2:
        return False
    ordinals = {match[1] for name in names if (match := _FANTIA_NUMBERED_PHOTO_PART.fullmatch(name))}
    if ordinals == {str(index) for index in range(1, len(names) + 1)}:
        return True
    base = min(names, key=len)
    label = base[len(title):].lstrip(" _") if base.startswith((title + "_", title + " ")) else base
    if not _FANTIA_PHOTO_PART_LABEL.fullmatch(label) or _WORK_VARIANT_LABEL.search(base):
        return False
    return names - {base} == {f"{base} ({index})" for index in range(1, len(names))}


def _fantia_version_title(title: str) -> bool:
    return title.casefold() in _VERSION_NAMES or _WORK_VARIANT_LABEL.search(title) is not None


def _fantia_id_post_sources(
    post: Path, entries: _DirectoryEntries, device: int, protected_roots: tuple[Path, ...],
) -> _OwnedMediaSources | None:
    """Claim the two exact-title photo folders of a single Fantia export ID."""
    if not _FANTIA_POST_COLLECTION.search(post.parent.name):
        return None
    wrappers = []
    totals: Counter[str] = Counter()
    for name, info in entries:
        path = post / name
        if info.st_dev != device or _protected(path, protected_roots) or is_reserved_workspace(path):
            return None
        if stat.S_ISDIR(info.st_mode):
            wrappers.append(name)
        elif stat.S_ISREG(info.st_mode) and _classify(name) == "V":
            totals["V"] += 1
        else:
            return None
    if len(wrappers) != 2:
        return None
    title, second = sorted(wrappers)
    if second != title + "_2" or _fantia_version_title(title):
        return None
    for name in wrappers:
        folder = post / name
        counts = _work_media_counts(folder, _regular_media_entries(folder, device), device, protected_roots)
        if not counts or set(counts) != {"P"}:
            return None
        totals.update(counts)
    return _OwnedMediaSources(set(wrappers), totals)


def _fantia_post_bucket_sources(
    post: Path, entries: list[tuple[str, os.stat_result]], device: int, protected_roots: tuple[Path, ...],
) -> _OwnedMediaSources | None:
    """Recognize media wrappers belonging to a single Fantia post."""
    if _FANTIA_POST_ID.fullmatch(post.name):
        return _fantia_id_post_sources(post, entries, device, protected_roots)
    title = _fantia_post_title(post)
    if title is None:
        return None
    totals: Counter[str] = Counter()
    has_bucket = False
    has_free_cover = False
    sources = []
    photo_parts: set[str] = set()
    title_layer = None
    for name, info in entries:
        path = post / name
        if info.st_dev != device or _protected(path, protected_roots) or is_reserved_workspace(path):
            return None
        if stat.S_ISREG(info.st_mode):
            kind = _classify(name)
            if kind not in {"P", "V"}:
                return None
            totals[kind] += 1
            continue
        if not stat.S_ISDIR(info.st_mode):
            return None
        bucket = MEDIA_BUCKET_PATTERN.fullmatch(name) is not None
        tier = _FANTIA_TIER.fullmatch(name) is not None
        label = _fantia_preview_label(name) if not (bucket or tier) else None
        photo_part = not (bucket or tier or label)
        if photo_part and name.endswith("_") and name.rstrip("_") == title and not _fantia_version_title(title):
            if title_layer is not None:
                return None
            title_layer = name
            photo_part = False
        if photo_part:
            photo_parts.add(name)
        has_bucket |= bucket
        has_free_cover |= label in _FANTIA_FREE_COVER_NAMES
        sources.append((name, info, bucket, label is not None or photo_part or name == title_layer))
    # A combined free and cover folder belongs at the post root even on its own.
    if not sources or not (totals or has_bucket or has_free_cover or len(sources) > 1):
        return None
    if title_layer is not None and not has_bucket:
        return None
    expected = _declared_fantia_totals(post) if photo_parts else None
    if photo_parts and (expected is None or expected["P"] < len(photo_parts) or totals - expected
                        or not _fantia_photo_parts(photo_parts, title)):
        return None
    try:
        for name, info, bucket, photo_only in sources:
            path = post / name
            folder, content = (post, [(name, info)]) if bucket else (path, _entries(path, device))
            counts = _work_media_counts(
                folder, content, device, protected_roots, allow_buckets=name != title_layer,
            )
            if not counts or (photo_only and set(counts) != {"P"}):
                return None
            totals.update(counts)
            if expected is not None and totals - expected:
                return None
    except (OSError, ValueError):
        return None
    if expected is not None and totals != expected:
        return None
    return _OwnedMediaSources({name for name, _, _, _ in sources}, totals)


def _verified_bucket_kind(path: Path, device: int) -> str | None:
    kind = _labelled_bucket_kind(path.name)
    if kind is not None:
        entries = _regular_media_entries(path, device)
        if entries and all(_classify(name) == kind for name, _ in entries):
            return kind
    return None


def _media_leaf_kinds(path: Path, device: int, protected_roots: tuple[Path, ...] = (), *,
                      allow_partial_bucketing: bool = True) -> set[str]:
    """Read media types from a leaf or its verified output buckets."""
    try:
        entries = _entries(path, device)
    except (OSError, ValueError):
        return set()
    kinds = set()
    for name, info in entries:
        if (info.st_dev != device or name.casefold().startswith(".nfc-")
                or _protected(path / name, protected_roots)):
            return set()
        if stat.S_ISREG(info.st_mode):
            kind = _classify(name)
        elif stat.S_ISDIR(info.st_mode):
            kind = _verified_bucket_kind(path / name, device)
            if kind is None:
                return set()
        else:
            return set()
        kinds.add(kind)
    if (not allow_partial_bucketing and kinds == {"P", "V"}
            and any(stat.S_ISREG(info.st_mode) for _, info in entries)
            and any(stat.S_ISDIR(info.st_mode) for _, info in entries)):
        return set()
    return kinds


def _default_folder_is_media_unit(path: Path, device: int, protected_roots: tuple[Path, ...] = ()) -> bool:
    """Confirm a default-named media leaf or its existing output buckets."""
    return (_DEFAULT_FOLDER.fullmatch(path.name) is not None
            and _media_leaf_kinds(path, device, protected_roots, allow_partial_bucketing=False)
            in ({"P"}, {"V"}, {"P", "V"}))


def _legacy_numbered_pv_pair(unit: Path, device: int, protected_roots: tuple[Path, ...]) -> bool:
    """Verify a numbered package consisting only of two correctly typed legacy buckets."""
    try:
        entries = _entries(unit, device)
    except (OSError, ValueError):
        return False
    if len(entries) != 2 or {name.upper() for name, _ in entries} != {"P", "V"}:
        return False
    for name, info in entries:
        folder = unit / name
        if not stat.S_ISDIR(info.st_mode) or info.st_dev != device or _protected(folder, protected_roots):
            return False
        files = _regular_media_entries(folder, device)
        counts = _work_media_counts(folder, files, device, protected_roots)
        if not counts or set(counts) != {name.upper()}:
            return False
    return True


def _numbered_siblings(unit: Path, entries: list[tuple[str, os.stat_result]],
                       device: int, protected_roots: tuple[Path, ...]) -> set[str]:
    """Confirm independent leaf packages using a collection name or a complete ordinal series."""
    directories = [name for name, info in entries if stat.S_ISDIR(info.st_mode)]
    if sum(bool(_NUMBERED_LEAF.fullmatch(name)) for name in directories) < 2:
        return set()
    names = [name for name in directories
             if _protected(unit / name, protected_roots) or not _verified_bucket_kind(unit / name, device)]
    ordinals = {name.lstrip("0") for name in names}
    if len(names) < 2 or "" in ordinals or len(names) != len(ordinals):
        return set()
    if not all(_NUMBERED_LEAF.fullmatch(name) and not _protected(unit / name, protected_roots) for name in names):
        return set()
    if ordinals == {str(index) for index in range(1, len(names) + 1)}:
        return {
            name for name in names
            if (_media_leaf_kinds(unit / name, device, protected_roots) in ({"P"}, {"V"}, {"P", "V"})
                or _legacy_numbered_pv_pair(unit / name, device, protected_roots))
        }
    if not _COLLECTION_CONTEXT.search(unit.name):
        return set()
    return set(names) if all(_media_leaf_kinds(unit / name, device) & {"P", "V"} for name in names) else set()


def _continuous_numbered_directories(
    unit: Path, entries: list[tuple[str, os.stat_result]], device: int, protected_roots: tuple[Path, ...], *,
    allow_named_peers: bool = False,
) -> set[str]:
    """Identify a complete sibling directory series starting at 1."""
    directories = [(name, info) for name, info in entries if stat.S_ISDIR(info.st_mode)
                   and (not allow_named_peers or _NUMBERED_LEAF.fullmatch(name))]
    if len(directories) < 2 or not all(
        _NUMBERED_LEAF.fullmatch(name) and info.st_dev == device and not _protected(unit / name, protected_roots)
        for name, info in directories
    ):
        return set()
    names = {name for name, _ in directories}
    ordinals = {name.lstrip("0") for name in names}
    return names if ordinals == {str(index) for index in range(1, len(names) + 1)} else set()


def _contains_only_named_works(
    unit: Path, entries: list[tuple[str, os.stat_result]], device: int, protected_roots: tuple[Path, ...],
) -> bool:
    """Confirm a numbered layer contains independent work directories and no files."""
    return bool(entries) and all(
        stat.S_ISDIR(info.st_mode) and info.st_dev == device and not _protected(unit / name, protected_roots)
        and not name.casefold().startswith(".nfc-")
        and (_COLLECTION_CONTEXT.search(name) or _WORK_FOLDER_MARKER.search(name))
        and not _is_wrapper(unit, name, device=device, protected_roots=protected_roots)
        for name, info in entries
    )


def _contains_verified_pack_series(
    unit: Path, entries: _DirectoryEntries, device: int, protected_roots: tuple[Path, ...],
) -> bool:
    """Keep a numbered volume when its children are independent packs of one series."""
    if not _NUMBERED_LEAF.fullmatch(unit.name) or len(entries) < 2:
        return False
    series: set[str] = set()
    ordinals: set[str] = set()
    for name, info in entries:
        match = _PACK_VOLUME_WORK.fullmatch(normalize("NFKC", name))
        pack = unit / name
        if (match is None or not stat.S_ISDIR(info.st_mode) or info.st_dev != device
                or _protected(pack, protected_roots) or is_reserved_workspace(pack)):
            return False
        series.add(match["series"].strip().casefold())
        ordinal = (match["bracketed"] or match["plain"]).lstrip("0")
        if (not ordinal or ordinal in ordinals
                or _media_leaf_kinds(pack, device, protected_roots) not in ({"P"}, {"V"}, {"P", "V"})):
            return False
        ordinals.add(ordinal)
    if len(series) != 1 or "" in series:
        return False
    try:
        peers = _entries(unit.parent, device)
    except (OSError, ValueError):
        return False
    return unit.name in _continuous_numbered_directories(
        unit.parent, peers, device, protected_roots, allow_named_peers=True,
    )


def _numbered_author_wrapper(entries: list[tuple[str, os.stat_result]]) -> str | None:
    """Find one numbered child beside the author's direct files."""
    if not any(stat.S_ISREG(info.st_mode) for _, info in entries):
        return None
    names = [name for name, info in entries
             if stat.S_ISDIR(info.st_mode) and _NUMBERED_LEAF.fullmatch(name)]
    return names[0] if len(names) == 1 else None


def _author_numbered_video_child(entries: list[tuple[str, os.stat_result]]) -> str | None:
    """Find one child beside a complete sequence of already numbered videos."""
    if not 2 <= len(entries) <= MAX_FILES_PER_GROUP:
        return None
    children = [name for name, info in entries if stat.S_ISDIR(info.st_mode)]
    files = sorted(name for name, info in entries if stat.S_ISREG(info.st_mode))
    if len(children) != 1 or len(files) != len(entries) - 1:
        return None
    if not all(_classify(name) == "V" and name == numbered_name(index, name)
               for index, name in enumerate(files, 1)):
        return None
    return children[0]


def _append_calendar_boundary(name: str) -> bool:
    """Preserve date-only labels while allowing a dated title with other words."""
    compact = "".join(name.split())
    return bool(_CALENDAR_DIRECTORY.fullmatch(compact) or _SHORT_CALENDAR_LABEL.fullmatch(compact))


def _author_initials_match(author: str, folder: str) -> bool:
    """Identify a Latin folder abbreviation computed from a Chinese author's name."""
    if (len(author) != len(folder) or len(folder) < 2 or not (folder.isascii() and folder.isalpha())
            or not all(unicode_name(char, "").startswith("CJK UNIFIED IDEOGRAPH-") for char in author)):
        return False
    from pypinyin import Style, lazy_pinyin

    return folder.casefold() == "".join(lazy_pinyin(author, style=Style.FIRST_LETTER))


def _whole_author_inventory(
    unit: Path, entries: list[tuple[str, os.stat_result]], device: int,
    protected_roots: tuple[Path, ...], check_cancelled: Callable[[], None] | None,
) -> tuple[list[dict], set[Path], bool] | None:
    """Discover a whole-author reorganization or an append to existing video numbers."""
    if (not _author_layer(unit) or _CALENDAR_DIRECTORY.fullmatch(unit.name)
            or not _CALENDAR_MONTH.fullmatch(unit.parent.parent.name)):
        return None
    name = _numbered_author_wrapper(entries)
    append_videos = name is None
    if append_videos:
        name = _author_numbered_video_child(entries)
        if name is None:
            return None
        label = name.strip().casefold()
        if (label.isdecimal() or _AMBIGUOUS.fullmatch(label)
                or _append_calendar_boundary(name) or _append_calendar_boundary(unit.name)
                or _RESOLUTION_NAME.fullmatch(label)
                or label in _VERSION_NAMES or label in _TYPED_WRAPPER_KINDS
                or _COLLECTION_CONTEXT.search(name) or _FANTIA_TIER.fullmatch(name)
                or _fantia_collection(unit) or _fantia_collection(unit / name)):
            return None
    kinds = {_classify(filename) for filename, info in entries if stat.S_ISREG(info.st_mode)}
    if kinds not in ({"P"}, {"V"}):
        return None
    child = unit / name
    try:
        if _protected(child, protected_roots):
            return None
        if append_videos:
            if _is_wrapper(unit, name, device=device, protected_roots=protected_roots):
                return None
            inner = _regular_media_entries(child, device)
            if (not inner or len(entries) - 1 + len(inner) > MAX_FILES_PER_GROUP
                    or any(_classify(filename) != "V" or _protected(child / filename, protected_roots)
                           for filename, _ in inner)
                    or (len(inner) > 1 and not _author_initials_match(unit.name, name))):
                return None
        else:
            inner = _entries(child, device)
            if (not any(stat.S_ISDIR(info.st_mode) for _, info in inner)
                    or {_classify(filename) for filename, info in inner if stat.S_ISREG(info.st_mode)} != kinds):
                return None
        directories: set[Path] = set()
        items = list(_semantic_inventory(
            unit, protected_roots, directories, whole_author=True, check_cancelled=check_cancelled,
        ))
    except (OSError, ValueError):
        return None
    if append_videos:
        expected = {str(unit / filename) for filename, info in entries if stat.S_ISREG(info.st_mode)}
        expected.update(str(child / filename) for filename, _ in inner)
        if directories != {unit, child} or {row["path"] for row in items} != expected:
            return None
    return (items, directories, append_videos) if {row["kind"] for row in items} == kinds else None


def _declared_media_count_label(unit: Path) -> str | None:
    """Read the sole bracketed media count label in a work title."""
    labels = [label for label in _BRACKETED_LABEL.findall(unit.name) if _MEDIA_COUNT_LABEL.search(label)]
    return labels[0] if len(labels) == 1 else None


def _declared_fantia_totals(post: Path) -> Counter[str] | None:
    """Read the declared photo count and any accompanying video count."""
    label = _declared_media_count_label(post)
    if label is None:
        return None
    photos = _PHOTO_PACK_TOTAL.fullmatch(label)
    if photos is not None:
        return Counter(P=int(photos[1]))
    mixed = _FANTIA_MIXED_POST_TOTAL.fullmatch(label)
    return Counter(P=int(mixed[1]), V=int(mixed[2])) if mixed is not None else None


def _declared_photo_total(unit: Path) -> int | None:
    """Read a photo-only count from a work label such as [123P 396.2MB]."""
    label = _declared_media_count_label(unit)
    match = _PHOTO_PACK_TOTAL.fullmatch(label) if label is not None else None
    return int(match.group(1)) if match else None


def _numbered_photo_groups_root(unit: Path, entries: list[tuple[str, os.stat_result]]) -> Path | None:
    """Locate the sole photo wrapper or the already-lifted numeric groups."""
    if len(entries) == 1:
        name, info = entries[0]
        if stat.S_ISDIR(info.st_mode) and name.casefold() in _PHOTO_ALIASES:
            return unit / name
    if len(entries) >= 2 and all(
        stat.S_ISDIR(info.st_mode) and _NUMBERED_LEAF.fullmatch(name) for name, info in entries
    ):
        return unit
    return None


def _numbered_photo_inventory(
    unit: Path, declared_count: int, device: int, protected_roots: tuple[Path, ...],
    check_cancelled: Callable[[], None] | None,
) -> tuple[list[dict], set[Path]] | None:
    """Verify numbered photo leaves and match the work's declared image count."""
    try:
        entries = _entries(unit, device)
        wrapper = _numbered_photo_groups_root(unit, entries)
        if wrapper is None or _protected(wrapper, protected_roots):
            return None
        groups = entries if wrapper == unit else _entries(wrapper, device)
        ordinals = {name.lstrip("0") for name, _ in groups}
        if (len(groups) < 2 or "" in ordinals or len(ordinals) != len(groups) or not all(
            stat.S_ISDIR(info.st_mode) and info.st_dev == device and _NUMBERED_LEAF.fullmatch(name)
            and not _protected(wrapper / name, protected_roots)
            for name, info in groups
        )):
            return None
        source_groups = {wrapper / name for name, _ in groups}
        directories: set[Path] = set()
        items = list(_semantic_inventory(
            unit, protected_roots, directories, whole_author=True, check_cancelled=check_cancelled,
        ))
    except (OSError, ValueError):
        return None
    files_by_group: dict[Path, list[str]] = {}
    for row in items:
        files_by_group.setdefault(Path(row["path"]).parent, []).append(row["name"])
    if (directories != {unit, wrapper, *source_groups} or files_by_group.keys() != source_groups
            or len(items) != declared_count or any(row["kind"] != "P" for row in items)
            or any(len(names) > MAX_FILES_PER_GROUP for names in files_by_group.values())):
        return None
    # Directly nested groups are only recognized as the completed output layout.
    if wrapper == unit and any(
        name != numbered_name(index, name)
        for names in files_by_group.values()
        for index, name in enumerate(sorted(names), 1)
    ):
        return None
    return items, directories


def preview_organizing_unit(
    unit: Path, *, mode: str, allowed_roots: list[Path],
    quarantine_root: Path | None = None, media_package_root: Path | None = None,
    max_rows: int = 100, include_items: bool = False, include_mapping: bool = False,
    local_media_kinds: tuple[str, ...] | None = None, whole_author: bool | None = None,
    local_scope: str | None = None,
    check_cancelled: Callable[[], None] | None = None,
) -> dict:
    """Plan an organizing unit. Only an unspecified whole-author scope is inferred."""
    unit = _checked_scope(unit, allowed_roots, quarantine_root)
    protected = _resolved_protected_roots(media_package_root, quarantine_root)
    if mode == "luolcy" and media_package_root is not None:
        if whole_author:
            if any(root.is_relative_to(unit) for root in _resolved_protected_roots(quarantine_root)):
                raise ValueError(f"Protected path inside Luolcy author directory: {unit}")
        else:
            unit = _package_path(unit, media_package_root, allowed_roots, quarantine_root)
    elif mode != "semantic" or _protected(unit, protected):
        raise ValueError("Invalid unit or mode")
    if (mode == "semantic" and not whole_author and local_scope is None
            and local_media_kinds is None and unit.name.casefold() == "v"):
        # A direct selection of V must use the same ownership as a recursive scan.
        device = os.lstat(unit).st_dev
        kinds, children = _direct_media_selection(unit, _entries(unit, device), device, protected)
        if any(name.casefold() in _VIDEO_WRAPPER_ALIASES for name in children):
            local_scope, local_media_kinds = DIRECT_MEDIA_SCOPE, kinds
    retained_bytes = 0
    retained_count = 0
    if local_scope == DIRECT_MEDIA_SCOPE:
        device = os.lstat(unit).st_dev
        direct_entries = _entries(unit, device)
        if local_media_kinds is None:
            local_media_kinds, _ = _direct_media_selection(unit, direct_entries, device, protected)
        for name, info in direct_entries:
            if stat.S_ISREG(info.st_mode) and _classify(name) == "Other":
                retained_count += 1
                retained_bytes += info.st_size
    photo_groups = None
    declared_count = _declared_photo_total(unit)
    if mode == "semantic" and not whole_author and not local_media_kinds and declared_count is not None:
        photo_groups = _numbered_photo_inventory(
            unit, declared_count, os.lstat(unit).st_dev, protected, check_cancelled,
        )
    author_inventory = None
    if photo_groups is None and mode == "semantic" and not whole_author and not local_media_kinds and local_scope is None:
        needs_layer_scope = local_media_kinds is None
        if (whole_author is None or needs_layer_scope) and (_author_layer(unit) or _local_wrapper_media_kind(unit)):
            device = os.lstat(unit).st_dev
            entries = _entries(unit, device)
            if whole_author is None:
                author_inventory = _whole_author_inventory(unit, entries, device, protected, check_cancelled)
            if (author_inventory is None and needs_layer_scope
                    and _semantic_branch_sources(unit, entries, device, protected) is None
                    and _work_media_component(unit, entries, device, protected) is None):
                local_media_kinds = _layer_media_kinds(unit, entries, device, protected)
    append_videos = False
    luolcy_siblings = {}
    root_fingerprint = None
    plan = None
    if mode == "luolcy" and whole_author:
        items, luolcy_siblings, nested_buckets = _luolcy_author_inventory(
            unit, media_package_root, check_cancelled=check_cancelled, lift_buckets=True,
        )
        if nested_buckets:
            root_fingerprint = _input_fingerprint(items, unit)
            plan = _plan_luolcy_bucket_lift(
                unit, nested_buckets, luolcy_siblings, {row["kind"] for row in items},
                max_rows=max_rows, include_items=include_items, include_mapping=include_mapping,
            )
            items = [row for bucket in nested_buckets.values() for row in bucket]
        directories = {unit}
    elif photo_groups is not None:
        items, directories = photo_groups
    elif author_inventory is not None:
        items, directories, append_videos = author_inventory
        whole_author = True
    else:
        directories = set()
        items = list(walk_organizing_unit(
            unit, mode=mode, media_package_root=media_package_root, quarantine_root=quarantine_root,
            directories=directories, local_media_kinds=local_media_kinds or (), whole_author=bool(whole_author),
            local_scope=local_scope, check_cancelled=check_cancelled,
        ))
    origin_dirs = set()
    for row in items:
        parent = Path(row["path"]).parent
        while parent != unit and parent not in origin_dirs:
            origin_dirs.add(parent)
            parent = parent.parent
    if plan is None:
        append_wrapper = False
        if mode == "semantic" and not whole_author and len(origin_dirs) == 1:
            branch, = origin_dirs
            append_wrapper = bool(
                (local_scope == DIRECT_MEDIA_SCOPE and unit.name.casefold() == "v"
                 and branch.name.casefold() in _VIDEO_WRAPPER_ALIASES)
                or (local_scope is None and _DEFAULT_FOLDER.fullmatch(branch.name)
                    and _PUBLISHED_WORK_DATE.match(unit.name))
            )
        plan = plan_media_layout(
            unit, items, max_rows=max_rows,
            include_items=include_items, include_mapping=include_mapping, organizer_mode=True,
            legacy_bucket_conflicts=not (mode == "semantic"
                                         and (photo_groups is not None or local_media_kinds
                                              or _CALENDAR_DIRECTORY.fullmatch(unit.name))),
            append_videos=append_videos,
            append_wrapper=append_wrapper,
            numbered_photo_groups=photo_groups is not None,
        )
    if mode == "semantic" and plan["status"] == "ready" and not (local_media_kinds or whole_author):
        held = _author_loose_record(unit, items, directories, protected)
        if held is not None:
            return held
    final_dirs = {Path(group["destination"]) for group in plan["groups"]}
    # A pre-existing empty branch is not an input. Retain its ancestors even
    # when another branch in the same wrapper supplied files.
    occupied_ancestors = {
        parent for empty in directories - origin_dirs - {unit}
        for parent in empty.parents if parent in origin_dirs
    }
    occupied_groups = final_dirs & occupied_ancestors
    scope = {"whole_author": True} if whole_author else {}
    if occupied_groups:
        return {**_blocked(unit, mode, "A target media bucket contains a non-input directory"), **scope}
    cleanup = origin_dirs - final_dirs - occupied_ancestors if plan["status"] == "ready" else set()
    if retained_count:
        plan["totals"]["Other"] += retained_count
        plan["total_files"] += retained_count
    return {
        **plan, "unit": str(unit), "organizer_mode": mode,
        **({"local_media_kinds": list(local_media_kinds)} if local_media_kinds else {}),
        **({"local_scope": local_scope} if local_scope is not None else {}),
        **scope,
        **({"luolcy_author_siblings": luolcy_siblings} if luolcy_siblings else {}),
        **({"luolcy_root_fingerprint": root_fingerprint} if root_fingerprint is not None else {}),
        **({"_luolcy_merged_children": sorted(str(path) for path in origin_dirs if path.parent == unit)}
           if mode == "luolcy" and whole_author else {}),
        "total_bytes": retained_bytes + sum(row["bytes"] for row in items),
        "wrapper_cleanup": sorted((str(path) for path in cleanup), key=lambda path: (-len(Path(path).parts), path)),
    }


def _semantic_previews(
    selection: Path, protected_roots: tuple[Path, ...], preview: Callable[..., dict],
    check_cancelled: Callable[[], None] | None,
) -> Iterator[dict]:
    device = os.lstat(selection).st_dev
    pending: list[tuple[Path, int, str | None]] = [(selection, 0, None)]
    visited = 0
    while pending:
        unit, depth, hold_reason = pending.pop()
        if check_cancelled is not None:
            check_cancelled()
        if hold_reason == _FINISH_REPEATED_ARCHIVE:
            try:
                archive = preview_repeated_archive(unit, protected_roots, check_cancelled=check_cancelled)
            except (OSError, ValueError) as exc:
                yield _blocked(unit, "semantic", str(exc))
            else:
                if archive is not None:
                    yield archive
            continue
        visited += 1
        if depth > MAX_DEPTH or visited > MAX_PACKAGE_DIRECTORIES:
            yield _blocked(unit, "semantic", "Media scope directory limit exceeded")
            continue
        try:
            entries = _entries(unit, device)
        except (OSError, ValueError) as exc:
            yield _blocked(unit, "semantic", str(exc))
            continue
        if hold_reason in {_NUMBERED_WORK_CONTAINER_CANDIDATE, _AMBIGUOUS_DIRECTORY_REASON}:
            named_works = (hold_reason == _NUMBERED_WORK_CONTAINER_CANDIDATE
                           and _contains_only_named_works(unit, entries, device, protected_roots))
            if named_works or _contains_verified_pack_series(unit, entries, device, protected_roots):
                # Keep the volume itself outside the plan. Its works get separate previews.
                pending.extend((unit / name, depth + 1, None) for name, _ in reversed(entries))
                continue
            hold_reason = _AMBIGUOUS_DIRECTORY_REASON
        if hold_reason is None:
            episode = _episode_inventory(unit, entries, device, protected_roots, check_cancelled)
            if episode is not None:
                row = preview(unit, "semantic", False)
                if (row["status"] != "blocked"
                        and row["input_fingerprint"] != _input_fingerprint(episode[0], unit)):
                    row = _blocked(unit, "semantic", "Episode contents changed during preview")
                yield row
                continue
        author_preview = None
        if (hold_reason is None and _author_layer(unit)
                and (_numbered_author_wrapper(entries) is not None or _author_numbered_video_child(entries) is not None)):
            author_preview = preview(unit, "semantic", None)
            if author_preview.get("whole_author"):
                # The whole author owns these files, so descendants cannot also become units.
                yield author_preview
                continue
        children: list[tuple[Path, int, str | None]] = []
        numbered = _numbered_siblings(unit, entries, device, protected_roots)
        if (hold_reason is None and not numbered and _declared_photo_total(unit) is not None
                and _numbered_photo_groups_root(unit, entries) is not None):
            photo_preview = preview(unit, "semantic", False)
            if photo_preview.get("operation") == PROMOTE_NUMBERED_PHOTO_GROUPS:
                yield photo_preview
                continue
        numbered_containers = _continuous_numbered_directories(unit, entries, device, protected_roots) - numbered
        owned_sources = (_semantic_branch_sources(unit, entries, device, protected_roots)
                         if hold_reason is None else None)
        if owned_sources is not None:
            row = preview(unit, "semantic", False)
            if row["status"] != "blocked" and Counter(row["totals"]) != owned_sources.totals:
                # Discovery claimed the children, so an ownership change requires a fresh scan.
                row = _blocked(unit, "semantic", "Work media count changed during preview")
            yield row
            continue
        repeated = _repeated_work_wrapper(unit, entries, device, protected_roots) if hold_reason is None else None
        work_component = (_work_media_component(unit, entries, device, protected_roots)
                          if hold_reason is None else None)
        pure_wrappers: list[Path] = []
        has_input = False
        for name, info in entries:
            child = unit / name
            if _protected(child, protected_roots):
                continue
            if name.casefold().startswith(".nfc-") or info.st_dev != device:
                yield _blocked(child, "semantic", "Reserved or cross-device entry")
            elif stat.S_ISDIR(info.st_mode):
                if (repeated is not None and repeated.is_relative_to(child)) or name == work_component:
                    pure_wrappers.append(child)
                elif _is_wrapper(unit, name, device=device, protected_roots=protected_roots):
                    if _pure_wrapper(child, device, protected_roots, check_cancelled):
                        pure_wrappers.append(child)
                    else:
                        children.append((child, depth + 1, _MIXED_WRAPPER_REASON))
                elif (_AMBIGUOUS.fullmatch(name) and name not in numbered and not _fantia_collection(unit)
                      and not _default_folder_is_media_unit(child, device, protected_roots)):
                    reason = (_NUMBERED_WORK_CONTAINER_CANDIDATE if name in numbered_containers
                              else _AMBIGUOUS_DIRECTORY_REASON)
                    children.append((child, depth + 1, reason))
                else:
                    children.append((child, depth + 1, None))
            elif stat.S_ISREG(info.st_mode):
                has_input = True
            else:
                yield _blocked(child, "semantic", "Symlink or special entry")
        row = None
        local_kinds = ()
        use_legacy_scope = (hold_reason == _MIXED_WRAPPER_REASON and _local_wrapper_media_kind(unit)
                            and _layer_media_kinds(unit, entries, device, protected_roots))
        if not use_legacy_scope and (
            hold_reason == _MIXED_WRAPPER_REASON
            or (hold_reason == _AMBIGUOUS_DIRECTORY_REASON and _NUMBERED_LEAF.fullmatch(unit.name))
        ):
            local_kinds, _ = _direct_media_selection(unit, entries, device, protected_roots)
        if local_kinds:
            row = preview(unit, "semantic", False, local_scope=DIRECT_MEDIA_SCOPE)
        elif use_legacy_scope:
            row = preview(unit, "semantic", False)
        elif hold_reason is not None:
            if hold_reason != _MIXED_WRAPPER_REASON or has_input or pure_wrappers:
                row = _held_files(unit, entries, hold_reason)
        elif has_input or pure_wrappers:
            row = author_preview if author_preview is not None else preview(unit, "semantic", False)
            if row.get("reason") == "作者层散文件待确认" and _calendar_author_layer(unit):
                local_kinds, _ = _direct_media_selection(unit, entries, device, protected_roots)
                if local_kinds:
                    row = preview(unit, "semantic", False, local_scope=DIRECT_MEDIA_SCOPE)
        if row is not None:
            if row.get("local_media_kinds"):
                if row.get("local_scope") == DIRECT_MEDIA_SCOPE:
                    _, claimed = _direct_media_selection(unit, entries, device, protected_roots)
                else:
                    claimed = {
                        child.name for child in pure_wrappers
                        if _labelled_bucket_kind(child.name) in row["local_media_kinds"]
                        and _verified_bucket_kind(child, device)
                    }
                # A local plan owns only its explicit buckets, so discovery
                # still needs to visit pure wrappers left outside that plan.
                children.extend((child, depth + 1, None) for child in pure_wrappers if child.name not in claimed)
            yield row
        children.sort(key=lambda entry: (str(entry[0]).casefold(), str(entry[0])), reverse=True)
        if is_repeated_archive(unit) and unit.parent.is_relative_to(selection):
            # Execute the media work under its original path before lifting directories.
            pending.append((unit, depth, _FINISH_REPEATED_ARCHIVE))
        pending.extend(children)


def iter_organizing_previews(
    selection: Path, *, allowed_roots: list[Path], quarantine_root: Path | None = None,
    media_package_root: Path | None = None,
    check_cancelled: Callable[[], None] | None = None,
    max_rows: int = 10, include_mapping: bool = False,
) -> Iterator[dict]:
    """Yield read-only previews from the selected scope."""
    selection = _checked_scope(selection, allowed_roots, quarantine_root)
    protected = _resolved_protected_roots(media_package_root, quarantine_root)
    package_root = Path(media_package_root) if media_package_root is not None else None

    def preview(path: Path, mode: str, whole_author: bool | None = False, *, local_scope: str | None = None) -> dict:
        try:
            return preview_organizing_unit(
                path, mode=mode, allowed_roots=allowed_roots,
                quarantine_root=quarantine_root, media_package_root=package_root,
                max_rows=max_rows, include_mapping=include_mapping, check_cancelled=check_cancelled,
                whole_author=whole_author, local_scope=local_scope,
            )
        except (OSError, ValueError) as exc:
            return _blocked(path, mode, str(exc))

    if package_root is None or not selection.is_relative_to(package_root):
        inventory = _PreviewDirectoryInventory()
        semantic = _semantic_previews(selection, protected, preview, check_cancelled)
        while True:
            token = _preview_inventory.set(inventory)
            try:
                row = next(semantic, None)
            finally:
                # Standalone and execution checks always read live entries.
                _preview_inventory.reset(token)
            if row is None:
                break
            yield row
        del inventory
    if package_root is not None and (
        selection.is_relative_to(package_root) or package_root.is_relative_to(selection)
    ):
        package_selection = selection if selection.is_relative_to(package_root) else package_root
        merged_children: set[Path] = set()
        try:
            for entry in iter_media_package_discovery(
                package_selection, media_package_root=package_root,
                allowed_roots=allowed_roots, quarantine_root=quarantine_root,
                isolate_conflicts=True, check_cancelled=check_cancelled, include_author_files=True,
            ):
                unit = entry.path
                if unit in merged_children:
                    merged_children.remove(unit)
                    continue
                if entry.reason:
                    yield _blocked(unit, "luolcy", entry.reason)
                elif entry.loose_files or entry.author_rebuild_candidate:
                    if is_reserved_workspace(unit) or (quarantine_root and unit.is_relative_to(quarantine_root)):
                        continue
                    if entry.author_rebuild_candidate:
                        row = preview(unit, "luolcy", True)
                        if row["status"] != "skipped":
                            if (row["status"] in {"ready", "already_organized"}
                                    or row.get("operation") == LIFT_LUOLCY_BUCKETS):
                                # A blocked lift still owns its input buckets. Do not independently renumber them.
                                merged_children.update(Path(path) for path in row["_luolcy_merged_children"])
                            yield row
                            continue
                    if not entry.loose_files:
                        continue
                    counts = Counter(row["kind"] for row in entry.loose_files)
                    yield {
                        **_blocked(unit, "luolcy", "作者层散件待确认归属"),
                        "status": "needs_assignment", "conflicts": [],
                        "totals": {kind: counts[kind] for kind in ("P", "V", "Other")},
                        "total_files": len(entry.loose_files),
                        "total_bytes": sum(row["bytes"] for row in entry.loose_files),
                        "_loose_files": entry.loose_files if include_mapping else [],
                        "_packages": {name: identity for name, identity in (entry.packages or {}).items()
                                      if not quarantine_root or not (unit / name).is_relative_to(quarantine_root)},
                        "_author_identity": entry.author_identity,
                    }
                else:
                    yield preview(unit, "luolcy")
        except (OSError, ValueError) as exc:
            yield _blocked(package_selection, "luolcy", str(exc))
