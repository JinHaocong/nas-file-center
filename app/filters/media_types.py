from __future__ import annotations

IMAGE_EXTENSIONS: frozenset[str] = frozenset({
    "jpg", "jpeg", "png", "webp", "gif", "bmp", "heic", "avif", "tiff", "svg"
})

VIDEO_EXTENSIONS: frozenset[str] = frozenset({
    "mp4", "mov", "mkv", "avi", "m4v", "mts", "m2ts", "webm", "ts", "flv", "wmv"
})

AUDIO_EXTENSIONS: frozenset[str] = frozenset({
    "mp3", "wav", "flac", "aac", "ogg", "m4a", "wma", "ape", "opus"
})

DOCUMENT_EXTENSIONS: frozenset[str] = frozenset({
    "pdf", "doc", "docx", "txt", "md", "rtf", "odt", "xls", "xlsx", "ppt", "pptx", "csv"
})

ARCHIVE_EXTENSIONS: frozenset[str] = frozenset({
    "zip", "tar", "gz", "tgz", "bz2", "tbz2", "xz", "txz", "7z", "rar", "iso"
})

MEDIA_TYPES: frozenset[str] = frozenset({
    "image", "video", "audio", "document", "archive", "other"
})


def normalize_extension(ext: str) -> str:
    """Normalize extension string: remove leading dot and lowercase."""
    clean = ext.strip().lower()
    if clean.startswith("."):
        clean = clean[1:]
    return clean


def get_media_type(ext: str) -> str:
    """Return media type category for a given extension."""
    norm = normalize_extension(ext)
    if norm in IMAGE_EXTENSIONS:
        return "image"
    if norm in VIDEO_EXTENSIONS:
        return "video"
    if norm in AUDIO_EXTENSIONS:
        return "audio"
    if norm in DOCUMENT_EXTENSIONS:
        return "document"
    if norm in ARCHIVE_EXTENSIONS:
        return "archive"
    return "other"


def get_extensions_for_media_type(media_type: str) -> frozenset[str]:
    """Return the set of known extensions for a media type category."""
    mt = media_type.strip().lower()
    if mt == "image":
        return IMAGE_EXTENSIONS
    if mt == "video":
        return VIDEO_EXTENSIONS
    if mt == "audio":
        return AUDIO_EXTENSIONS
    if mt == "document":
        return DOCUMENT_EXTENSIONS
    if mt == "archive":
        return ARCHIVE_EXTENSIONS
    return frozenset()
