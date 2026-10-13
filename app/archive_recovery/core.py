"""Bounded, non-overwriting salvage of independently readable archive entries.

No external extractor ever receives a writable NAS pathname. Entries are copied
through directory descriptors into a fresh private result directory.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import os
from pathlib import Path, PurePosixPath
import re
import stat
import struct
import tarfile
import time
import zipfile
import zlib
from typing import Callable, Iterator

from PIL import Image

CHUNK = 128 * 1024
MAX_FILES = 10000
MAX_BYTES = 4 * 1024**3
MAX_SECONDS = 1800
MAX_DEPTH = 32


class RecoveryError(Exception):
    """A controlled error which does not imply a bad password."""


def detect_format(source: Path) -> str:
    """Identify the container from magic bytes, never from its suffix alone."""
    with source.open('rb') as fd:
        header = fd.read(600)
    if header.startswith((b'PK\x03\x04', b'PK\x05\x06', b'PK\x07\x08')):
        return 'zip'
    if header.startswith(b'7z\xbc\xaf\x27\x1c'):
        return '7z'
    if header.startswith((b'Rar!\x1a\x07\x00', b'Rar!\x1a\x07\x01\x00')):
        return 'rar'
    if header[257:262] == b'ustar':
        return 'tar'
    if header.startswith((b'\x1f\x8b', b'\xfd7zXZ\x00', b'BZh')):
        if any(source.name.lower().endswith(s) for s in ('.tar.gz', '.tgz', '.tar.xz', '.txz', '.tar.bz2', '.tbz2')):
            return 'tar'
    raise RecoveryError('UNSUPPORTED_FORMAT: only ZIP, TAR, 7z and RAR are supported')


def safe_parts(raw: str) -> tuple[str, ...]:
    """Reject untrusted names before creating ANY path component."""
    if not raw or '\x00' in raw or raw.startswith(('/', '\\')) or re.match(r'^[A-Za-z]:', raw):
        raise RecoveryError('UNSAFE_PATH')
    path = PurePosixPath(raw.replace('\\', '/'))
    parts = path.parts
    if (not parts or len(parts) > MAX_DEPTH or any(p in ('', '.', '..') for p in raw.replace('\\','/').split('/'))
            or any(':' in p or len(os.fsencode(p)) > 240 for p in parts)
            or any(p == '_incomplete' or p.startswith('.nfc-part-') for p in parts)):
        raise RecoveryError('UNSAFE_PATH')
    return parts


def _open_parent(root_fd: int, parts: tuple[str, ...]) -> int:
    """Open/create parents only via no-follow directory descriptors."""
    current = os.dup(root_fd)
    try:
        for component in parts[:-1]:
            try:
                os.mkdir(component, mode=0o700, dir_fd=current)
            except FileExistsError:
                pass
            nxt = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current)
            os.close(current)
            current = nxt
        return current
    except BaseException:
        os.close(current)
        raise


def _status(root: Path, rel: str, *, integrity: bool) -> str:
    if integrity:
        return 'integrity_passed'
    if Path(rel).suffix.lower() not in {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.tif', '.tiff'}:
        return 'unverified'
    try:
        with Image.open(root / rel) as img:
            img.verify()
        with Image.open(root / rel) as img:
            img.load()
        return 'format_validated'
    except Exception:
        return 'incomplete'


class Budget:
    """One counter shared by every nested extraction and salvage strategy."""
    def __init__(self, check: Callable[[], None] | None = None):
        self.count = 0
        self.bytes = 0
        self.start = time.monotonic()
        self.check = check or (lambda: None)

    def step(self, size: int = 0, *, new_file: bool = False) -> None:
        self.check()
        if time.monotonic() - self.start > MAX_SECONDS:
            raise RecoveryError('TIME_LIMIT')
        self.bytes += size
        self.count += int(new_file)
        if self.bytes > MAX_BYTES or self.count > MAX_FILES:
            raise RecoveryError('RESOURCE_LIMIT')


def _record(root: Path, root_fd: int, raw: str, chunks: Iterator[bytes], budget: Budget,
            results: list[dict], *, crc: bool = False, expected: int | None = None,
            provenance: str = 'archive') -> None:
    """Commit a single entry only after reading it; quarantine corrupt bytes."""
    try:
        parts = safe_parts(raw)
    except RecoveryError:
        results.append({'name': raw[:256], 'status': 'unrecovered', 'reason': 'UNSAFE_PATH'})
        return
    budget.step(new_file=True)
    parent = _open_parent(root_fd, parts)
    temporary = '.nfc-part-' + os.urandom(12).hex()
    total = 0
    err = None
    opened = False
    try:
        try:
            out = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
            opened = True
        except FileExistsError:
            raise RecoveryError('WORKSPACE_CONFLICT')
        try:
            with os.fdopen(out, 'wb') as handle:
                try:
                    for block in chunks:
                        budget.step(len(block))
                        handle.write(block)
                        total += len(block)
                except (EOFError, OSError, ValueError, RuntimeError, zlib.error, zipfile.BadZipFile, tarfile.TarError) as exc:
                    err = type(exc).__name__
                handle.flush()
                os.fsync(handle.fileno())
        except BaseException:
            # Cancellation/lease loss must propagate; entry stays private and
            # is removed by the enclosing finally, not published as good.
            raise
        if expected is not None and total != expected:
            err = err or 'TRUNCATED'
        name = '/'.join(parts)
        if err:
            inc = os.open('_incomplete', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
            try:
                published = os.path.basename(parts[-1])[:100] + '-' + os.urandom(5).hex() + '.partial'
                os.rename(temporary, published, src_dir_fd=parent, dst_dir_fd=inc)
            finally:
                os.close(inc)
            results.append({'name': name, 'status': 'incomplete', 'bytes': total,
                            'reason': err, 'provenance': provenance, 'path': '_incomplete/' + published})
        else:
            try:
                # Link-based exclusive publication: never replace an existing result.
                os.link(temporary, parts[-1], src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
                os.unlink(temporary, dir_fd=parent)
            except FileExistsError:
                os.unlink(temporary, dir_fd=parent)
                results.append({'name': name, 'status': 'unrecovered', 'reason': 'OUTPUT_CONFLICT'})
                return
            status = _status(root, name, integrity=crc)
            if status == 'incomplete':
                inc = os.open('_incomplete', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
                try:
                    published = parts[-1][:100] + '-' + os.urandom(5).hex() + '.partial'
                    os.rename(parts[-1], published, src_dir_fd=parent, dst_dir_fd=inc)
                finally:
                    os.close(inc)
                results.append({'name': name, 'status': status, 'bytes': total,
                                'reason': 'FORMAT_DECODE_FAILED', 'provenance': provenance,
                                'path': '_incomplete/' + published})
            else:
                results.append({'name': name, 'path': name, 'status': status,
                                'bytes': total, 'provenance': provenance})
    finally:
        if opened:
            try:
                os.unlink(temporary, dir_fd=parent)
            except FileNotFoundError:
                pass
        os.close(parent)


def _zip(source: Path, root: Path, fd: int, budget: Budget, results: list[dict], password: str | None, deep: bool) -> int | None:
    try:
        archive = zipfile.ZipFile(source)
    except zipfile.BadZipFile:
        if not deep:
            raise RecoveryError('DAMAGED_ZIP_DIRECTORY') from None
        return _zip_headers(source, root, fd, budget, results)
    with archive:
        members = archive.infolist()
        if len(members) > MAX_FILES:
            raise RecoveryError('RESOURCE_LIMIT')
        for member in members:
            budget.step()
            if member.is_dir():
                continue
            if (member.external_attr >> 16) & 0o170000 in (stat.S_IFLNK, stat.S_IFCHR, stat.S_IFBLK, stat.S_IFIFO, stat.S_IFSOCK):
                results.append({'name': member.filename, 'status': 'unrecovered', 'reason': 'NON_REGULAR_ENTRY'})
                continue
            try:
                stream = archive.open(member, pwd=password.encode('utf-8') if password else None)
            except (RuntimeError, NotImplementedError, zipfile.BadZipFile, ValueError) as exc:
                results.append({'name': member.filename, 'status': 'unrecovered',
                                'reason': 'PASSWORD_OR_DATA_ERROR' if member.flag_bits & 1 else type(exc).__name__})
                continue
            with stream:
                _record(root, fd, member.filename, iter(lambda: stream.read(CHUNK), b''), budget,
                        results, crc=True, expected=member.file_size)
        return sum(not m.is_dir() for m in members)


def _zip_headers(source: Path, root: Path, fd: int, budget: Budget, results: list[dict]) -> None:
    """Conservative salvage: only complete non-encrypted local headers without descriptors."""
    with source.open('rb') as inp:
        length = source.stat().st_size
        offset = 0
        while offset + 30 <= length:
            budget.step()
            inp.seek(offset)
            sig = inp.read(4)
            if sig != b'PK\x03\x04':
                # A candidate must still pass strict header, stream and CRC
                # checks; arbitrary signatures are never considered valid.
                inp.seek(offset)
                window = inp.read(CHUNK)
                next_header = window.find(b'PK\x03\x04', 1)
                offset += next_header if next_header >= 0 else max(1, len(window) - 3)
                continue
            hdr = inp.read(26)
            if len(hdr) != 26:
                break
            _, flags, method, _, _, crc, compressed, raw_size, name_len, extra_len = struct.unpack('<HHHHHIIIHH', hdr)
            if name_len > 4096 or extra_len > 65535 or compressed > MAX_BYTES:
                offset += 4
                continue
            raw = inp.read(name_len)
            extra = inp.read(extra_len)
            if len(raw) != name_len or len(extra) != extra_len:
                offset += 4
                continue
            name = raw.decode('utf-8' if flags & 0x800 else 'cp437', errors='replace')
            if flags & (1 | 8) or method not in (0, 8) or raw_size > MAX_BYTES:
                results.append({'name': name, 'status': 'unrecovered', 'reason': 'LOCAL_HEADER_UNSUPPORTED'})
                offset = inp.tell() + compressed
                continue
            # The compressed region is bounded; decompression is streaming and
            # budget accounting occurs before data is written. Malformed streams
            # cannot allocate their declared uncompressed length in memory.
            def unpack_chunks() -> Iterator[bytes]:
                remaining = compressed
                digest = 0
                plain_size = 0
                dec = zlib.decompressobj(-15) if method == 8 else None
                while remaining:
                    part = inp.read(min(CHUNK, remaining))
                    if not part:
                        raise EOFError('TRUNCATED')
                    remaining -= len(part)
                    if dec is None:
                        blocks = (part,)
                    else:
                        blocks = []
                        while part:
                            out = dec.decompress(part, CHUNK)
                            part = dec.unconsumed_tail
                            if not out and not part:
                                break
                            blocks.append(out)
                    for decoded in blocks:
                        digest = zlib.crc32(decoded, digest)
                        plain_size += len(decoded)
                        yield decoded
                if dec is not None and not dec.eof:
                    raise EOFError('STREAM_TRUNCATED')
                if plain_size != raw_size or (digest & 0xffffffff) != crc:
                    raise ValueError('CRC_MISMATCH')
            _record(root, fd, name, unpack_chunks(), budget, results, crc=True,
                    expected=raw_size, provenance=f'zip_local_header@{offset}')
            offset = inp.tell()
        return None


def _tar_header(block: bytes) -> tuple[str, int, bytes] | None:
    if len(block) != 512 or block[257:262] != b'ustar':
        return None
    try:
        raw_sum = int(block[148:156].strip(b' \x00') or b'0', 8)
        if sum(block[:148]) + sum(b' ' * 8) + sum(block[156:]) != raw_sum:
            return None
        size = int(block[124:136].strip(b' \x00') or b'0', 8)
        raw_name = block[:100].split(b'\0')[0]
        prefix = block[345:500].split(b'\0')[0]
        name = (prefix + b'/' if prefix else b'') + raw_name
        if not name or size > MAX_BYTES:
            return None
        return (name.decode('utf-8', errors='surrogateescape'), size, block[156:157])
    except (ValueError, OverflowError):
        return None


def _raw_tar(source: Path, root: Path, fd: int, budget: Budget, results: list[dict]) -> None:
    """Rescan 512-byte TAR alignment; header checksum is NOT payload integrity."""
    with source.open('rb') as inp:
        offset = 0
        length = source.stat().st_size
        while offset + 512 <= length:
            budget.step()
            inp.seek(offset)
            block = inp.read(512)
            if block == b'\0' * 512:
                offset += 512
                continue
            header = _tar_header(block)
            if header is None:
                offset += 512
                continue
            name, size, kind = header
            if kind not in (b'0', b'\x00', b'5'):
                results.append({'name': name, 'status': 'unrecovered', 'reason': 'NON_REGULAR_ENTRY'})
            elif kind != b'5':
                available = min(size, max(0, length - offset - 512))
                inp.seek(offset + 512)
                def chunks() -> Iterator[bytes]:
                    left = available
                    while left:
                        part = inp.read(min(CHUNK, left))
                        if not part:
                            break
                        left -= len(part)
                        yield part
                _record(root, fd, name, chunks(), budget, results, expected=size,
                        provenance=f'tar_header@{offset}')
            offset += 512 + ((size + 511) // 512) * 512
    return None


def _stream_tar(source: Path, root: Path, fd: int, budget: Budget, results: list[dict]) -> None:
    try:
        with tarfile.open(source, mode='r|*') as tf:
            for member in tf:
                budget.step()
                if not member.isfile():
                    if member.issym() or member.islnk():
                        results.append({'name': member.name, 'status': 'unrecovered', 'reason': 'NON_REGULAR_ENTRY'})
                    continue
                stream = tf.extractfile(member)
                if stream is None:
                    results.append({'name': member.name, 'status': 'unrecovered', 'reason': 'DATA_UNAVAILABLE'})
                    continue
                _record(root, fd, member.name, iter(lambda: stream.read(CHUNK), b''), budget,
                        results, expected=member.size, provenance='tar_stream')
    except (tarfile.TarError, OSError, EOFError):
        return


def _libarchive(source: Path, root: Path, fd: int, budget: Budget, results: list[dict], password: str | None) -> None:
    """Use libarchive's stream reader; NEVER call its disk extraction writer."""
    name = ctypes.util.find_library('archive')
    if not name:
        raise RecoveryError('DEPENDENCY_MISSING: libarchive')
    lib = ctypes.CDLL(name)
    def api(fn: str, args: list, ret=ctypes.c_int):
        f = getattr(lib, fn)
        f.argtypes = args
        f.restype = ret
        return f
    ptr = ctypes.c_void_p
    new = api('archive_read_new', [], ptr)
    filters = api('archive_read_support_filter_all', [ptr])
    formats = api('archive_read_support_format_all', [ptr])
    passwd = api('archive_read_add_passphrase', [ptr, ctypes.c_char_p])
    opn = api('archive_read_open_filename', [ptr, ctypes.c_char_p, ctypes.c_size_t])
    nxt = api('archive_read_next_header', [ptr, ctypes.POINTER(ptr)])
    ename = api('archive_entry_pathname', [ptr], ctypes.c_char_p)
    etype = api('archive_entry_filetype', [ptr])
    esize = api('archive_entry_size', [ptr], ctypes.c_int64)
    data = api('archive_read_data', [ptr, ptr, ctypes.c_size_t], ctypes.c_ssize_t)
    err = api('archive_error_string', [ptr], ctypes.c_char_p)
    free = api('archive_read_free', [ptr])
    handle = new()
    if not handle:
        raise RecoveryError('DEPENDENCY_ERROR')
    try:
        filters(handle)
        formats(handle)
        if password:
            passwd(handle, password.encode('utf-8'))
        if opn(handle, os.fsencode(source), CHUNK) != 0:
            raise RecoveryError('PASSWORD_OR_DATA_ERROR')
        entry = ptr()
        while True:
            budget.step()
            rc = nxt(handle, ctypes.byref(entry))
            if rc == 1:  # ARCHIVE_EOF
                break
            if rc != 0:
                results.append({'name': '<archive>', 'status': 'unrecovered',
                                'reason': 'PASSWORD_OR_DATA_ERROR' if password else 'DAMAGED_ARCHIVE'})
                break
            raw = ename(entry)
            path = raw.decode('utf-8', errors='replace') if raw else '<unnamed>'
            if etype(entry) != stat.S_IFREG:
                if etype(entry) != stat.S_IFDIR:
                    results.append({'name': path, 'status': 'unrecovered', 'reason': 'NON_REGULAR_ENTRY'})
                continue
            size = esize(entry)
            if size < 0 or size > MAX_BYTES:
                raise RecoveryError('RESOURCE_LIMIT')
            def chunks() -> Iterator[bytes]:
                buff = ctypes.create_string_buffer(CHUNK)
                while True:
                    n = data(handle, buff, CHUNK)
                    if n == 0:
                        break
                    if n < 0:
                        raise OSError('ARCHIVE_DATA_ERROR')
                    yield buff.raw[:n]
            _record(root, fd, path, chunks(), budget, results, expected=size, provenance='libarchive')
    finally:
        free(handle)


def recover_archive(source: Path, result_dir: Path, *, password: str | None = None,
                    check: Callable[[], None] | None = None, deep: bool = True,
                    items: list[dict] | None = None) -> dict:
    """Recover entries to an EMPTY, caller-owned directory; never touch source."""
    source = Path(source)
    result_dir = Path(result_dir)
    if source.is_symlink() or not source.is_file() or not result_dir.is_dir() or result_dir.is_symlink():
        raise RecoveryError('INVALID_SOURCE_OR_DESTINATION')
    fmt = detect_format(source)
    if any(result_dir.iterdir()):
        raise RecoveryError('DESTINATION_NOT_EMPTY')
    os.mkdir(result_dir / '_incomplete', mode=0o700)
    fd = os.open(result_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    budget = Budget(check)
    results: list[dict] = items if items is not None else []
    try:
        if fmt == 'zip':
            total = _zip(source, result_dir, fd, budget, results, password, deep)
        elif fmt == 'tar':
            total = None
            with source.open('rb') as reader:
                raw_tar = reader.read(262)[257:262] == b'ustar'
            if raw_tar:
                _raw_tar(source, result_dir, fd, budget, results)
            else:
                _stream_tar(source, result_dir, fd, budget, results)
        else:
            total = None
            _libarchive(source, result_dir, fd, budget, results, password)
        # One additional TAR layer, only from a normally published regular file.
        if deep:
            for record in list(results):
                if record.get('status') not in {'integrity_passed', 'unverified', 'format_validated', 'incomplete'}:
                    continue
                if not record['name'].lower().endswith('.tar'):
                    continue
                inner = result_dir / record['path']
                before = len(results)
                _raw_tar(inner, result_dir, fd, budget, results)
                if len(results) > before:
                    inner.unlink()
                    results.remove(record)
        return {'format': fmt, 'source': str(source), 'output': str(result_dir),
                'known_total': total, 'items': results,
                'stats': {s: sum(r['status'] == s for r in results)
                          for s in ('integrity_passed','format_validated','unverified','incomplete','unrecovered')},
                'deep_capability': 'tar_inner_only' if fmt in ('7z', 'rar') else 'tar_or_zip_salvage',
                'warnings': ['Format validation is not byte-for-byte integrity verification.',
                             'Encrypted solid LZMA2 / RAR stream resynchronization is not supported.']}
    finally:
        os.close(fd)
        try:
            (result_dir / '_incomplete').rmdir()
        except OSError:
            pass


def clean_interrupted_parts(output: Path, identity: list[str]) -> int:
    """Delete ONLY our exact temporary names under a verified private output root.

    Final files, even in nested user directories, are never removed. The same
    temp-name namespace is forbidden to archive entries by safe_parts().
    """
    if output.is_symlink() or not output.is_dir():
        return 0
    observed = output.stat()
    if [str(observed.st_dev), str(observed.st_ino)] != identity:
        return 0
    count = 0
    for parent, dirs, files in os.walk(output, topdown=True, followlinks=False):
        if Path(parent).is_symlink():
            continue
        dirs[:] = [name for name in dirs if not (Path(parent) / name).is_symlink()]
        for name in files:
            if re.fullmatch(r"\.nfc-part-[0-9a-f]{24}", name):
                path = Path(parent) / name
                if path.is_symlink():
                    continue
                path.unlink(missing_ok=True)
                count += 1
    return count