from __future__ import annotations

import math
from typing import Any

from app.organizers.templates import (
    ALLOWED_RENAME_VARS,
    ALLOWED_STATISTICS_VARS,
    validate_and_normalize_extensions,
    validate_cleanup_patterns,
    validate_template,
)

DEFAULT_ORGANIZER_RECURSIVE: bool = False
DEFAULT_ORGANIZER_IMAGE_EXTENSIONS: list[str] = ["jpg", "jpeg", "png", "webp"]
DEFAULT_ORGANIZER_VIDEO_EXTENSIONS: list[str] = ["mp4", "mov", "mkv"]
DEFAULT_ORGANIZER_RENAME_TEMPLATE: str = "{name}"
DEFAULT_ORGANIZER_STATISTICS_TEMPLATE: str = "[{images}P {videos}V {size}]"
DEFAULT_ORGANIZER_PRESERVE_TAGS: list[str] = []
DEFAULT_ORGANIZER_CLEANUP_PATTERNS: list[str] = []
DEFAULT_ORGANIZER_NUMBERING_MODE: str = "none"
DEFAULT_ORGANIZER_NUMBERING_START: int = 1
DEFAULT_ORGANIZER_NUMBERING_PADDING: int = 3
DEFAULT_ORGANIZER_MTIME_MODE: str = "none"
DEFAULT_ORGANIZER_MTIME_DELAY_SECONDS: float = 2.0


def validate_profile_name(name: Any) -> str:
    if not isinstance(name, str):
        raise ValueError("方案名称不能为空")
    cleaned = name.strip()
    if not cleaned:
        raise ValueError("方案名称不能为空")
    return cleaned


def normalize_preserve_tags(tags: Any) -> list[str]:
    if tags is None:
        return []
    if not isinstance(tags, list):
        raise ValueError("preserve_tags 必须为列表")
    cleaned: list[str] = []
    for t in tags:
        if isinstance(t, bool) or not isinstance(t, str):
            raise ValueError("preserve_tags 元素必须为字符串")
        st = t.strip()
        if st:
            cleaned.append(st)
    return cleaned[:20]


def validate_and_normalize_image_extensions(exts: Any) -> list[str]:
    if exts is None:
        return list(DEFAULT_ORGANIZER_IMAGE_EXTENSIONS)
    if not isinstance(exts, list):
        raise ValueError("image_extensions 必须为列表")
    for item in exts:
        if isinstance(item, bool) or not isinstance(item, str):
            raise ValueError("image_extensions 元素必须为字符串")
    return validate_and_normalize_extensions(exts, "image_extensions")


def validate_and_normalize_video_extensions(exts: Any) -> list[str]:
    if exts is None:
        return list(DEFAULT_ORGANIZER_VIDEO_EXTENSIONS)
    if not isinstance(exts, list):
        raise ValueError("video_extensions 必须为列表")
    for item in exts:
        if isinstance(item, bool) or not isinstance(item, str):
            raise ValueError("video_extensions 元素必须为字符串")
    return validate_and_normalize_extensions(exts, "video_extensions")


def validate_rename_template(template: Any) -> str:
    s = str(template if template is not None else DEFAULT_ORGANIZER_RENAME_TEMPLATE).strip()
    errors = validate_template(s, ALLOWED_RENAME_VARS)
    if errors:
        raise ValueError(errors[0])
    return s


def validate_statistics_template(template: Any) -> str:
    s = str(template if template is not None else DEFAULT_ORGANIZER_STATISTICS_TEMPLATE).strip()
    errors = validate_template(s, ALLOWED_STATISTICS_VARS)
    if errors:
        raise ValueError(errors[0])
    return s


def validate_profile_cleanup_patterns(patterns: Any) -> list[str]:
    if patterns is None:
        return []
    if not isinstance(patterns, list):
        raise ValueError("cleanup_patterns 必须为列表")
    for p in patterns:
        if isinstance(p, bool) or not isinstance(p, str):
            raise ValueError("cleanup_patterns 元素必须为字符串")
    errors = validate_cleanup_patterns(patterns)
    if errors:
        raise ValueError(errors[0])
    return patterns
