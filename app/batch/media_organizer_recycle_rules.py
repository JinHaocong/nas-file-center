"""Read-only candidates for the media organizer's optional recycle action."""

import os
from pathlib import Path
import re
import stat
from codecs import BOM_UTF8, BOM_UTF16_BE, BOM_UTF16_LE
from urllib.parse import urlsplit

from app.batch.file_rename import _open_directory_nofollow

_MAX_TEXT_BYTES = 64 * 1024
_LINK = re.compile(r"https?://[^\s<>\"'，。；、]+", re.I)
_PROMOTION_LABEL = r"(?:广告|广告链接|推广|推广链接|推广信息|公众号推广)"
_PROMOTION_HEADING = re.compile(rf"(?:【{_PROMOTION_LABEL}】|\[{_PROMOTION_LABEL}\]|{_PROMOTION_LABEL})(?:\s*[:：]\s*(.*))?")
_PROMOTION_VISIT = re.compile(r"(?:更多|获取更多)(?:资源|福利|更新)(?:请)?(?:访问|点击|查看)\s*[:：]?\s*(.+)")
_PROMOTION_CONTACT = re.compile(
    r"(?:敬请|请|欢迎)?(?:关注(?:微信)?公众号|扫码关注|扫码加群|加入(?:QQ|微信)?群)"
    r"(?:\s*[:：]\s*[\w.·-]{1,40}|\s+[\w.·-]{1,40})?",
    re.I,
)
_PROMOTION_REWARD = re.compile(r"(?:请|欢迎)?(?:加群|扫码|关注公众号)(?:领取|获取)(?:更多)?(?:资源|福利|更新)")
_BINARY_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")


def _identity(info: os.stat_result) -> tuple[int, ...]:
    return info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _only_links(line: str) -> bool:
    """Accept complete HTTP(S) URLs and exclude prose around a link."""
    for value in line.split():
        if not _LINK.fullmatch(value):
            return False
        try:
            url = urlsplit(value)
            if not url.hostname or url.username is not None:
                return False
            # Reading port validates the authority rather than accepting e.g. :oops.
            url.port
        except ValueError:
            return False
    return bool(line.strip())


def _promotion_command(line: str) -> bool:
    visit = _PROMOTION_VISIT.fullmatch(line)
    return (_only_links(visit[1]) if visit else bool(
        _PROMOTION_CONTACT.fullmatch(line) or _PROMOTION_REWARD.fullmatch(line)
    ))


def _promotion_line(line: str) -> bool:
    heading = _PROMOTION_HEADING.fullmatch(line)
    if heading:
        rest = (heading[1] or "").strip()
        return not rest or _only_links(rest) or _promotion_command(rest)
    return _promotion_command(line)


def _decode_text(payload: bytes) -> str | None:
    """Support explicit BOMs, UTF-8 and GB18030 without dropping invalid bytes."""
    if payload.startswith((BOM_UTF16_LE, BOM_UTF16_BE)):
        encodings = ("utf-16",)
    elif payload.startswith(BOM_UTF8):
        encodings = ("utf-8-sig",)
    else:
        encodings = ("utf-8", "gb18030")
    for encoding in encodings:
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    return None


def _text_reason(payload: bytes) -> str | None:
    content = _decode_text(payload)
    if not content or _BINARY_CONTROL.search(content):
        return None
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    if not lines:
        return None
    if all(_only_links(line) for line in lines):
        return "links_only"
    if all(_only_links(line) or _promotion_line(line) for line in lines):
        return "promotion"
    return None


def check(path: Path, expected_stat: os.stat_result) -> str | None:
    """Classify one unchanged regular file without following a file or directory symlink."""
    suffix = path.suffix.casefold()
    if (suffix not in {".url", ".txt"} or not stat.S_ISREG(expected_stat.st_mode)
            or not path.is_absolute() or ".." in path.parts):
        return None
    if suffix == ".txt" and not 0 < expected_stat.st_size <= _MAX_TEXT_BYTES:
        return None
    expected = _identity(expected_stat)
    try:
        parent = _open_directory_nofollow(path.parent)
        try:
            if _identity(os.stat(path.name, dir_fd=parent, follow_symlinks=False)) != expected:
                return None
            if suffix == ".url":
                return "url_shortcut"
            fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            try:
                if _identity(os.fstat(fd)) != expected:
                    return None
                payload = os.pread(fd, _MAX_TEXT_BYTES + 1, 0)
                if (len(payload) != expected_stat.st_size or _identity(os.fstat(fd)) != expected
                        or _identity(os.stat(path.name, dir_fd=parent, follow_symlinks=False)) != expected):
                    return None
            finally:
                os.close(fd)
        finally:
            os.close(parent)
    except OSError:
        return None
    return _text_reason(payload)
