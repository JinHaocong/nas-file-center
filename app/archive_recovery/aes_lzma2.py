"""Conservative 7z LZMA2 solid-stream resynchronization (plain or AES-CBC).

This is NOT plaintext reconstruction. We map LZMA2 chunks to the CRC-checked
7z header's uncompressed offsets. Only complete, independently decodable files
whose original 7z per-file CRC32 matches are published. Unknown boundaries,
unsupported folder graphs, encrypted headers, or lost chunk framing fail closed.

A CBC ciphertext error may corrupt the corresponding plaintext block and the
next block; later LZMA2 dictionary resets can still be independently decoded.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import lzma
from pathlib import Path
import struct
from typing import Callable, Iterator
import zlib

try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
except ImportError:  # fail-closed; this feature is optional outside the packaged runtime
    Cipher = algorithms = modes = None

HEADER_LIMIT = 16 * 1024 * 1024
FRAME_OUTPUT_LIMIT = 2 * 1024 * 1024
SEGMENT_LIMIT = 32 * 1024 * 1024
MAX_SCAN_BYTES = 8 * 1024**3
LZMA2_ID = b'\x21'
AES_ID = b'\x06\xf1\x07\x01'


class DeepRecoveryUnavailable(Exception):
    """Unsupported or unverifiable archive layout, never a recovery success."""


class Parse:
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def raw(self, n: int) -> bytes:
        if n < 0 or self.pos + n > len(self.data):
            raise DeepRecoveryUnavailable('TRUNCATED_7Z_HEADER')
        chunk = self.data[self.pos:self.pos+n]
        self.pos += n
        return chunk

    def u8(self) -> int:
        return self.raw(1)[0]

    def num(self) -> int:
        first = self.u8()
        mask = 0x80
        for n in range(8):
            if not first & mask:
                value = (first & (mask - 1)) << (8 * n)
                for i in range(n):
                    value |= self.u8() << (8 * i)
                return value
            mask >>= 1
        return int.from_bytes(self.raw(8), 'little')

    def tag(self, wanted: int) -> None:
        if self.u8() != wanted:
            raise DeepRecoveryUnavailable('UNSUPPORTED_7Z_HEADER_LAYOUT')


def _digest_list(p: Parse, count: int) -> list[int | None]:
    if count > 10000:
        raise DeepRecoveryUnavailable('TOO_MANY_SUBSTREAMS')
    all_defined = p.u8()
    if all_defined:
        defined = [True] * count
    else:
        bits = p.raw((count + 7) // 8)
        defined = [bool(bits[i // 8] & (0x80 >> (i % 8))) for i in range(count)]
    return [struct.unpack('<I', p.raw(4))[0] if d else None for d in defined]


def _folder(p: Parse) -> tuple[list[tuple[bytes, bytes]], list[tuple[int, int]]]:
    count = p.num()
    if count < 1 or count > 4:
        raise DeepRecoveryUnavailable('UNSUPPORTED_7Z_FOLDER')
    coders: list[tuple[bytes, bytes]] = []
    for _ in range(count):
        flags = p.u8()
        if flags & 0xD0:  # complex, alternative, reserved method
            raise DeepRecoveryUnavailable('UNSUPPORTED_7Z_CODER_GRAPH')
        method = p.raw(flags & 0x0F)
        props = p.raw(p.num()) if flags & 0x20 else b''
        if len(props) > 64:
            raise DeepRecoveryUnavailable('INVALID_CODER_PROPERTIES')
        coders.append((method, props))
    binds = [(p.num(), p.num()) for _ in range(count - 1)]
    # Every coder above has exactly one input and output; one packed stream.
    return coders, binds


def _stream_info(p: Parse) -> dict:
    result: dict = {}
    count = 0
    while True:
        tag = p.u8()
        if tag == 0:
            break
        if tag == 6:
            pos = p.num()
            count = p.num()
            if count != 1:
                raise DeepRecoveryUnavailable('MULTIPLE_PACKED_STREAMS')
            p.tag(9)
            sizes = [p.num() for _ in range(count)]
            next_tag = p.u8()
            if next_tag == 10:
                _digest_list(p, count)
                next_tag = p.u8()
            if next_tag != 0:
                raise DeepRecoveryUnavailable('UNSUPPORTED_PACK_INFO')
            result.update(pack_pos=pos, pack_size=sizes[0])
        elif tag == 7:
            p.tag(11)
            folders = p.num()
            if folders != 1 or p.u8() != 0:
                raise DeepRecoveryUnavailable('MULTIPLE_OR_EXTERNAL_FOLDERS')
            coders, binds = _folder(p)
            p.tag(12)
            sizes = [p.num() for _ in coders]
            nxt = p.u8()
            folder_crc = None
            if nxt == 10:
                folder_crc = _digest_list(p, 1)[0]
                nxt = p.u8()
            if nxt != 0:
                raise DeepRecoveryUnavailable('UNSUPPORTED_UNPACK_INFO')
            result.update(coders=coders, binds=binds, unpack_sizes=sizes, folder_crc=folder_crc)
        elif tag == 8:
            if 'coders' not in result:
                raise DeepRecoveryUnavailable('MISORDERED_7Z_STREAMS')
            nsub = 1
            subt = p.u8()
            if subt == 13:
                nsub = p.num()
                subt = p.u8()
            if nsub < 1 or nsub > 10000:
                raise DeepRecoveryUnavailable('INVALID_SUBSTREAM_COUNT')
            known = []
            if subt == 9:
                known = [p.num() for _ in range(nsub - 1)]
                subt = p.u8()
            elif nsub > 1:
                raise DeepRecoveryUnavailable('MISSING_SUBSTREAM_SIZES')
            # The final coder in a linear 2-coder pipeline is the LZMA2 output.
            total = result['unpack_sizes'][-1]
            sizes = known + [total - sum(known)]
            if sizes[-1] < 0:
                raise DeepRecoveryUnavailable('INVALID_SUBSTREAM_SIZES')
            crcs = [None] * nsub
            if subt == 10:
                if nsub == 1 and result.get('folder_crc') is not None:
                    raise DeepRecoveryUnavailable('DUPLICATE_FOLDER_CRC')
                crcs = _digest_list(p, nsub)
                subt = p.u8()
            elif nsub == 1:
                crcs = [result.get('folder_crc')]
            if subt != 0:
                raise DeepRecoveryUnavailable('UNSUPPORTED_SUBSTREAM_INFO')
            result.update(sub_sizes=sizes, sub_crcs=crcs)
        else:
            raise DeepRecoveryUnavailable('UNKNOWN_STREAM_INFO')
    if not {'pack_pos','pack_size','coders','binds','unpack_sizes'} <= result.keys():
        raise DeepRecoveryUnavailable('INCOMPLETE_STREAM_METADATA')
    result.setdefault('sub_sizes', [result['unpack_sizes'][-1]])
    result.setdefault('sub_crcs', [result.get('folder_crc')])
    return result


def _file_info(p: Parse, stream: dict) -> list[tuple[str, int, int, int | None]]:
    count = p.num()
    if count < 1 or count > 10000:
        raise DeepRecoveryUnavailable('INVALID_FILE_COUNT')
    names: list[str] | None = None
    nonempty = [True] * count
    while True:
        tag = p.u8()
        if tag == 0:
            break
        length = p.num()
        if length > HEADER_LIMIT:
            raise DeepRecoveryUnavailable('FILE_PROPERTY_TOO_LARGE')
        sub = Parse(p.raw(length))
        if tag == 14:  # kEmptyStream bit vector
            bits = sub.raw((count + 7)//8)
            nonempty = [not bool(bits[i // 8] & (0x80 >> (i % 8))) for i in range(count)]
        elif tag == 17:
            if sub.u8() != 0:
                raise DeepRecoveryUnavailable('EXTERNAL_FILENAMES_UNSUPPORTED')
            chars = sub.raw(len(sub.data) - sub.pos)
            if len(chars) % 2 or not chars.endswith(b'\x00\x00'):
                raise DeepRecoveryUnavailable('INVALID_FILENAMES')
            try:
                names = chars.decode('utf-16-le').split('\x00')[:-1]
            except UnicodeError as exc:
                raise DeepRecoveryUnavailable('INVALID_FILENAMES') from exc
        # Other metadata properties are length-delimited and ignored.
    if names is None or len(names) != count or sum(nonempty) != len(stream['sub_sizes']):
        raise DeepRecoveryUnavailable('FILE_MAPPING_UNAVAILABLE')
    out: list[tuple[str, int, int, int | None]] = []
    offset = 0
    n = 0
    for name, present in zip(names, nonempty):
        if not present:
            continue
        length = stream['sub_sizes'][n]
        out.append((name, offset, length, stream['sub_crcs'][n]))
        offset += length
        n += 1
    if offset != stream['unpack_sizes'][-1]:
        raise DeepRecoveryUnavailable('UNPACK_SIZES_MISMATCH')
    return out


def _read_header(p: Parse) -> tuple[dict, list[tuple[str, int, int, int | None]]]:
    p.tag(1)
    tag = p.u8()
    if tag != 4:
        raise DeepRecoveryUnavailable('UNSUPPORTED_HEADER_PROPERTIES')
    stream = _stream_info(p)
    p.tag(5)
    files = _file_info(p, stream)
    p.tag(0)
    if p.pos != len(p.data):
        raise DeepRecoveryUnavailable('TRAILING_HEADER_DATA')
    return stream, files


def _dictionary_size(prop: bytes) -> int:
    if len(prop) != 1 or prop[0] > 40:
        raise DeepRecoveryUnavailable('INVALID_LZMA2_PROPERTIES')
    n = prop[0]
    if n == 40:
        raise DeepRecoveryUnavailable('UNBOUNDED_LZMA2_DICTIONARY')
    size = (2 | (n & 1)) << (n // 2 + 11)
    if size > 32 * 1024**2:
        raise DeepRecoveryUnavailable('LZMA2_DICTIONARY_TOO_LARGE')
    return size


def _decode_header(raw: bytes, source: Path, file_size: int) -> bytes:
    """Decode simple unencrypted LZMA2 metadata headers, or accept plain ones."""
    if raw.startswith(b'\x01'):
        return raw
    p = Parse(raw)
    p.tag(23)
    stream = _stream_info(p)
    if p.pos != len(raw) or len(stream['coders']) != 1 or stream['coders'][0][0] != LZMA2_ID:
        raise DeepRecoveryUnavailable('ENCRYPTED_OR_COMPLEX_7Z_HEADER')
    offset = 32 + stream['pack_pos']
    packed = stream['pack_size']
    if packed > HEADER_LIMIT or offset + packed > file_size:
        raise DeepRecoveryUnavailable('INVALID_PACKED_HEADER')
    with source.open('rb') as file:
        file.seek(offset)
        contents = file.read(packed)
    try:
        dec = lzma.LZMADecompressor(format=lzma.FORMAT_RAW, filters=[
            {'id': lzma.FILTER_LZMA2, 'dict_size': _dictionary_size(stream['coders'][0][1])}
        ])
        out = dec.decompress(contents, max_length=HEADER_LIMIT + 1)
    except lzma.LZMAError as exc:
        raise DeepRecoveryUnavailable('INVALID_ENCODED_HEADER') from exc
    if len(out) != stream['unpack_sizes'][-1] or not dec.eof or len(out) > HEADER_LIMIT:
        raise DeepRecoveryUnavailable('INVALID_ENCODED_HEADER')
    if stream.get('folder_crc') is not None and zlib.crc32(out) != stream['folder_crc']:
        raise DeepRecoveryUnavailable('ENCODED_HEADER_CRC_MISMATCH')
    return out


@dataclass(frozen=True)
class Metadata:
    offset: int
    packed_size: int
    unpacked_size: int
    dictionary: int
    aes_props: bytes | None
    files: list[tuple[str, int, int, int | None]]


def inspect_7z(source: Path) -> Metadata:
    with source.open('rb') as file:
        intro = file.read(32)
        size = source.stat().st_size
        if len(intro) != 32 or intro[:6] != b'7z\xbc\xaf\x27\x1c':
            raise DeepRecoveryUnavailable('NOT_7Z')
        if zlib.crc32(intro[12:32]) != struct.unpack('<I', intro[8:12])[0]:
            raise DeepRecoveryUnavailable('START_HEADER_CRC_MISMATCH')
        next_offset, next_size, next_crc = struct.unpack('<QQI', intro[12:32])
        if next_size > HEADER_LIMIT or next_offset + next_size + 32 > size:
            raise DeepRecoveryUnavailable('INVALID_NEXT_HEADER_BOUNDS')
        file.seek(32 + next_offset)
        raw = file.read(next_size)
    if zlib.crc32(raw) != next_crc:
        raise DeepRecoveryUnavailable('NEXT_HEADER_CRC_MISMATCH')
    stream, files = _read_header(Parse(_decode_header(raw, source, size)))
    coders, binds = stream['coders'], stream['binds']
    if len(coders) == 2 and [x[0] for x in coders] == [AES_ID, LZMA2_ID] and binds == [(1, 0)]:
        aes_props = coders[0][1]
        lzma_props = coders[1][1]
    elif len(coders) == 1 and coders[0][0] == LZMA2_ID and not binds:
        aes_props = None
        lzma_props = coders[0][1]
    else:
        raise DeepRecoveryUnavailable('NOT_AES_OR_PLAIN_LZMA2_LINEAR_FOLDER')
    dictionary = _dictionary_size(lzma_props)
    packed = stream['pack_size']
    offset = 32 + stream['pack_pos']
    if not 0 < packed <= MAX_SCAN_BYTES or (aes_props is not None and packed % 16) or offset + packed > size:
        raise DeepRecoveryUnavailable('INVALID_LZMA2_PACKED_RANGE')
    if not any(crc is not None for _, _, _, crc in files):
        raise DeepRecoveryUnavailable('NO_PER_FILE_CRCS')
    return Metadata(offset=offset, packed_size=packed,
        unpacked_size=stream['unpack_sizes'][-1], dictionary=dictionary,
        aes_props=aes_props, files=files)


def _key_and_iv(props: bytes, password: str) -> tuple[bytes, bytes]:
    if not props:
        raise DeepRecoveryUnavailable('AES_PROPERTIES_MISSING')
    b0 = props[0]
    cycles = b0 & 0x3F
    if b0 & 0xC0:
        if len(props) < 2:
            raise DeepRecoveryUnavailable('AES_PROPERTIES_INVALID')
        salt_len = (b0 >> 7) + (props[1] >> 4)
        iv_len = ((b0 >> 6) & 1) + (props[1] & 0x0F)
        if len(props) != 2 + salt_len + iv_len or salt_len > 16 or iv_len > 16:
            raise DeepRecoveryUnavailable('AES_PROPERTIES_INVALID')
        salt = props[2:2+salt_len]
        iv = props[2+salt_len:]
    else:
        if len(props) != 1:
            raise DeepRecoveryUnavailable('AES_PROPERTIES_INVALID')
        salt, iv = b'', b''
    pass_utf16 = password.encode('utf-16-le')
    if cycles == 63:
        key = (salt + pass_utf16).ljust(32, b'\0')[:32]
    elif cycles <= 20:
        digest = hashlib.sha256()
        prefix = salt + pass_utf16
        for n in range(1 << cycles):
            digest.update(prefix)
            digest.update(struct.pack('<Q', n))
        key = digest.digest()
    else:
        raise DeepRecoveryUnavailable('AES_KDF_TOO_EXPENSIVE')
    return key, iv.ljust(16, b'\0')


class DecryptedStream:
    """Bounded read of LZMA2 bytes, with CBC decryption only when required."""
    def __init__(self, source: Path, meta: Metadata, password: str | None, check: Callable[[], None]):
        if meta.aes_props is not None:
            if not password:
                raise DeepRecoveryUnavailable('PASSWORD_REQUIRED')
            if Cipher is None:
                raise DeepRecoveryUnavailable('CRYPTOGRAPHY_NOT_INSTALLED')
            key, iv = _key_and_iv(meta.aes_props, password)
            decoder = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
        else:
            decoder = None  # The packed stream is already LZMA2; no password needed.
        self.file = source.open('rb')
        self.file.seek(meta.offset)
        self.remaining = meta.packed_size
        self.decoder = decoder
        self.buffer = bytearray()
        self.consumed = 0
        self.check = check

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.file.close()

    def read(self, n: int) -> bytes:
        if n < 0 or n > FRAME_OUTPUT_LIMIT:
            raise DeepRecoveryUnavailable('INVALID_CHUNK_SIZE')
        while len(self.buffer) < n and self.remaining:
            self.check()
            count = min(self.remaining, 256 * 1024)
            block = self.file.read(count)
            if len(block) != count:
                raise DeepRecoveryUnavailable('PACKED_DATA_TRUNCATED')
            self.remaining -= count
            self.buffer.extend(self.decoder.update(block) if self.decoder is not None else block)
        if len(self.buffer) < n:
            raise DeepRecoveryUnavailable('PACKED_STREAM_EXHAUSTED')
        out = bytes(self.buffer[:n])
        del self.buffer[:n]
        self.consumed += n
        return out


@dataclass
class Frame:
    raw: bytes
    decoded_size: int
    input_offset: int
    output_offset: int
    reset: bool


def _frames(stream: DecryptedStream, check: Callable[[], None]) -> Iterator[Frame]:
    """Only trust offsets while the entire LZMA2 framing remains parseable."""
    output = 0
    while stream.remaining or stream.buffer:
        check()
        start = stream.consumed
        control = stream.read(1)[0]
        if control == 0:
            return
        if control in (1, 2):
            size = int.from_bytes(stream.read(2), 'big') + 1
            raw = bytes([control]) + (size - 1).to_bytes(2, 'big') + stream.read(size)
        elif control >= 0x80:
            sizes = stream.read(4)
            size = ((control & 31) << 16) + int.from_bytes(sizes[:2], 'big') + 1
            compressed = int.from_bytes(sizes[2:], 'big') + 1
            if size > FRAME_OUTPUT_LIMIT or compressed > 65536:
                raise DeepRecoveryUnavailable('DAMAGED_LZMA2_FRAMING')
            props = stream.read(1) if control >= 0xC0 else b''
            if props and (props[0] >= 225 or (props[0] % 9) + ((props[0] // 9) % 5) > 4):
                raise DeepRecoveryUnavailable('DAMAGED_LZMA2_PROPERTIES')
            raw = bytes([control]) + sizes + props + stream.read(compressed)
        else:
            raise DeepRecoveryUnavailable('DAMAGED_LZMA2_FRAMING')
        yield Frame(raw=raw, decoded_size=size, input_offset=start,
                    output_offset=output, reset=control == 1 or control >= 0xE0)
        output += size


def _decode_segment(frames: list[Frame], dictionary: int) -> bytes:
    if not frames or not frames[0].reset:
        raise DeepRecoveryUnavailable('MISSING_LZMA2_RESET')
    try:
        dec = lzma.LZMADecompressor(format=lzma.FORMAT_RAW, filters=[
            {'id': lzma.FILTER_LZMA2, 'dict_size': dictionary}
        ])
        result = bytearray()
        for frame in frames:
            piece = dec.decompress(frame.raw, max_length=frame.decoded_size + 1)
            if len(piece) != frame.decoded_size:
                raise DeepRecoveryUnavailable('CORRUPTED_LZMA2_CHUNK')
            result.extend(piece)
            if len(result) > SEGMENT_LIMIT:
                raise DeepRecoveryUnavailable('SEGMENT_LIMIT')
        return bytes(result)
    except (lzma.LZMAError, EOFError) as exc:
        raise DeepRecoveryUnavailable('CORRUPTED_LZMA2_CHUNK') from exc


def recover_aes_lzma2(source: Path, password: str | None, *, check: Callable[[], None],
                       publish: Callable[[str, Iterator[bytes], int, str], bool]) -> dict:
    """Publish *only* CRC-proven complete file ranges; no unknown-offset bytes.

    `publish` receives (name, chunks, exact_size, provenance) and must use the
    existing guarded descriptor-based result publisher. Returns True on success.
    """
    meta = inspect_7z(source)
    provenance_prefix = '7z_aes_lzma2' if meta.aes_props is not None else '7z_lzma2'
    recovered = 0
    reset_points = 0
    segments = 0
    rejected = 0
    current: list[Frame] = []
    current_size = 0
    prior = 0
    attempted: set[str] = set()

    def flush() -> None:
        nonlocal recovered, segments, rejected
        if not current or not current[0].reset:
            return
        segments += 1
        start = current[0].output_offset
        length = current_size
        if length > SEGMENT_LIMIT:
            rejected += 1
            return
        try:
            decoded = _decode_segment(current, meta.dictionary)
        except DeepRecoveryUnavailable:
            rejected += 1
            return
        for name, offset, size, crc in meta.files:
            check()
            if crc is None or name in attempted or not size:
                continue
            if offset < start or offset + size > start + len(decoded):
                continue
            blob = decoded[offset-start:offset-start+size]
            if zlib.crc32(blob) != crc:
                continue
            attempted.add(name)
            if publish(name, iter((blob,)), size,
                       f'{provenance_prefix}_reset@{current[0].input_offset}'):
                recovered += 1

    with DecryptedStream(source, meta, password, check) as stream:
        try:
            for frame in _frames(stream, check):
                if frame.output_offset != prior:
                    raise DeepRecoveryUnavailable('OUTPUT_OFFSET_DISCONTINUITY')
                prior += frame.decoded_size
                if prior > meta.unpacked_size:
                    raise DeepRecoveryUnavailable('UNPACKED_SIZE_MISMATCH')
                if frame.reset:
                    reset_points += 1
                    flush()
                    current = []
                    current_size = 0
                current.append(frame)
                current_size += frame.decoded_size
                if len(current) > 32768 or current_size > SEGMENT_LIMIT:
                    # Never retain arbitrarily long segments; continue framing
                    # to discover later dictionary-reset boundaries.
                    current = []
                    current_size = 0
            flush()
        except DeepRecoveryUnavailable as exc:
            # Framing is lost; offsets are unknown. Independently probe later
            # reset streams and publish ONLY an exact CRC-proven whole file.
            # All intermediate bytes remain in memory and are discarded.
            rescanned = _resync_by_full_file_crc(stream, meta, check, publish, attempted,
                                                 provenance_prefix=provenance_prefix)
            recovered += rescanned['proven_files']
            return {'status': 'framing_resynchronized' if rescanned['proven_files'] else 'framing_lost',
                    'reason': str(exc), 'recovered': recovered,
                    'reset_points': reset_points, 'decoded_segments': segments,
                    'rejected_segments': rejected, 'resync_scan': rescanned}
    return {'status': 'completed' if recovered else 'no_proven_files', 'recovered': recovered,
            'reset_points': reset_points, 'decoded_segments': segments,
            'rejected_segments': rejected}


def _frame_from_bytes(buffer: bytes, start: int) -> tuple[Frame, int] | None:
    """Parse one LZMA2 frame at an unknown offset without trusting its prefix."""
    if start >= len(buffer):
        return None
    control = buffer[start]
    if control in (1, 2):
        if start + 3 > len(buffer):
            return None
        size = int.from_bytes(buffer[start+1:start+3], 'big') + 1
        end = start + 3 + size
    elif control >= 0x80:
        if start + 6 > len(buffer):
            return None
        size = ((control & 31) << 16) + int.from_bytes(buffer[start+1:start+3], 'big') + 1
        packed = int.from_bytes(buffer[start+3:start+5], 'big') + 1
        header = 6 if control >= 0xC0 else 5
        if size > FRAME_OUTPUT_LIMIT or packed > 65536:
            return None
        if control >= 0xC0:
            prop = buffer[start+5]
            if prop >= 225 or (prop % 9) + ((prop // 9) % 5) > 4:
                return None
        end = start + header + packed
    else:
        return None
    if end > len(buffer):
        return None
    return Frame(buffer[start:end], size, start, 0, control == 1 or control >= 0xE0), end


def _resync_by_full_file_crc(stream: DecryptedStream, meta: Metadata,
                             check: Callable[[], None],
                             publish: Callable[[str, Iterator[bytes], int, str], bool],
                             already_attempted: set[str], *, provenance_prefix: str = '7z_aes_lzma2') -> dict:
    """Bounded search after broken framing; no absolute offsets are guessed.

    If the reset segment EXACTLY covers a CRC-bearing source file, that full
    file can be verified against its archived name, length and checksum without
    guessing missing uncompressed offsets. CRC32 is not cryptographic proof. Subranges are never guessed.
    """
    window = bytearray()
    cap = 8 * 1024**2
    remaining = stream.remaining + len(stream.buffer)
    while len(window) < cap and remaining:
        check()
        part = stream.read(min(256 * 1024, cap - len(window), remaining))
        window.extend(part)
        remaining -= len(part)
    data = bytes(window)
    targets: dict[int, list[tuple[str, int]]] = {}
    for name, _, size, crc in meta.files:
        if crc is not None and 0 < size <= SEGMENT_LIMIT and name not in already_attempted:
            targets.setdefault(size, []).append((name, crc))
    if not targets:
        return {'scan_bytes': len(data), 'probed': 0, 'proven_files': 0}
    biggest = max(targets)
    probed, proven = 0, 0
    for pos, control in enumerate(data):
        if not (control == 1 or control >= 0xE0):
            continue
        if pos % 4096 == 0:
            check()
        parsed = _frame_from_bytes(data, pos)
        if parsed is None or not parsed[0].reset:
            continue
        probed += 1
        if probed > 12000:
            break
        frames: list[Frame] = []
        idx = pos
        size = 0
        for _ in range(64):
            part = _frame_from_bytes(data, idx)
            if part is None:
                break
            frame, next_pos = part
            if frame.reset and frames:
                break
            frames.append(frame)
            size += frame.decoded_size
            idx = next_pos
            if size > biggest or size > SEGMENT_LIMIT:
                break
            if size not in targets:
                continue
            try:
                decoded = _decode_segment(frames, meta.dictionary)
            except DeepRecoveryUnavailable:
                break
            checksum = zlib.crc32(decoded)
            for name, expected_crc in targets.get(size, []):
                if name not in already_attempted and checksum == expected_crc:
                    already_attempted.add(name)
                    if publish(name, iter((decoded,)), size,
                               f'{provenance_prefix}_crc_resync@{pos}'):
                        proven += 1
            if size == biggest:
                break
    return {'scan_bytes': len(data), 'probed': probed, 'proven_files': proven}