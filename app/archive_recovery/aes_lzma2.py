"""Conservative 7z LZMA2 solid-stream resynchronization (plain or AES-CBC).

This is NOT plaintext reconstruction. We map LZMA2 chunks to the CRC-checked
7z header's uncompressed offsets. Only complete, independently decodable files
whose original 7z per-file CRC32 matches are published. Unknown boundaries,
unsupported folder graphs, unverifiable headers, or lost chunk framing fail closed.

A CBC ciphertext error may corrupt the corresponding plaintext block and the
next block; later LZMA2 dictionary resets can still be independently decoded.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import lzma
from pathlib import Path
import struct
import tempfile
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
LZMA1_ID = b'\x03\x01\x01'
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
    """Read every independent packed folder and its ordered file substreams.

    A linear 7z folder has one packed stream even with multiple coders.
    PackInfo and SubStreamsInfo are arrays over *all* folders; treating the
    archive as one folder loses the later streams and their CRC boundaries.
    """
    pack_pos = None
    packed_sizes: list[int] | None = None
    folders: list[dict] | None = None
    sub_counts: list[int] | None = None
    per_folder_sizes: list[list[int]] | None = None
    per_folder_crcs: list[list[int | None]] | None = None
    while True:
        tag = p.u8()
        if tag == 0:
            break
        if tag == 6:
            if packed_sizes is not None:
                raise DeepRecoveryUnavailable('DUPLICATE_PACK_INFO')
            pack_pos = p.num()
            count = p.num()
            if count < 1 or count > 10000:
                raise DeepRecoveryUnavailable('INVALID_PACKED_STREAM_COUNT')
            p.tag(9)
            packed_sizes = [p.num() for _ in range(count)]
            next_tag = p.u8()
            if next_tag == 10:
                _digest_list(p, count)  # optional packed CRC; damaged packs can be salvaged
                next_tag = p.u8()
            if next_tag != 0:
                raise DeepRecoveryUnavailable('UNSUPPORTED_PACK_INFO')
        elif tag == 7:
            if folders is not None:
                raise DeepRecoveryUnavailable('DUPLICATE_UNPACK_INFO')
            p.tag(11)
            count = p.num()
            if count < 1 or count > 10000 or p.u8() != 0:
                raise DeepRecoveryUnavailable('MULTIPLE_OR_EXTERNAL_FOLDERS')
            folders = []
            for _ in range(count):
                coders, binds = _folder(p)
                folders.append({'coders': coders, 'binds': binds})
            p.tag(12)
            for block in folders:
                block['unpack_sizes'] = [p.num() for _ in block['coders']]
            next_tag = p.u8()
            crcs = [None] * count
            if next_tag == 10:
                crcs = _digest_list(p, count)
                next_tag = p.u8()
            if next_tag != 0:
                raise DeepRecoveryUnavailable('UNSUPPORTED_UNPACK_INFO')
            for block, crc in zip(folders, crcs):
                block['folder_crc'] = crc
        elif tag == 8:
            if folders is None or sub_counts is not None:
                raise DeepRecoveryUnavailable('MISORDERED_7Z_STREAMS')
            sub_counts = [1] * len(folders)
            subt = p.u8()
            if subt == 13:
                sub_counts = [p.num() for _ in folders]
                subt = p.u8()
            if any(n < 1 or n > 10000 for n in sub_counts) or sum(sub_counts) > 10000:
                raise DeepRecoveryUnavailable('INVALID_SUBSTREAM_COUNT')
            if subt == 9:
                lengths = [p.num() for _ in range(sum(n - 1 for n in sub_counts))]
                subt = p.u8()
            elif any(n > 1 for n in sub_counts):
                raise DeepRecoveryUnavailable('MISSING_SUBSTREAM_SIZES')
            else:
                lengths = []
            cursor = 0
            per_folder_sizes = []
            for block, count in zip(folders, sub_counts):
                leading = lengths[cursor:cursor + count - 1]
                cursor += count - 1
                final = block['unpack_sizes'][-1] - sum(leading)
                if final < 0:
                    raise DeepRecoveryUnavailable('INVALID_SUBSTREAM_SIZES')
                per_folder_sizes.append(leading + [final])
            # 7z omits per-substream digest when exactly one substream
            # inherits the containing folder's unpack CRC.
            needs_crc = sum(n for n, block in zip(sub_counts, folders)
                            if n != 1 or block['folder_crc'] is None)
            if subt == 10:
                extra_crcs = _digest_list(p, needs_crc)
                subt = p.u8()
            else:
                extra_crcs = [None] * needs_crc
            if subt != 0:
                raise DeepRecoveryUnavailable('UNSUPPORTED_SUBSTREAM_INFO')
            per_folder_crcs = []
            cursor = 0
            for count, block in zip(sub_counts, folders):
                if count == 1 and block['folder_crc'] is not None:
                    per_folder_crcs.append([block['folder_crc']])
                else:
                    per_folder_crcs.append(extra_crcs[cursor:cursor + count])
                    cursor += count
        else:
            raise DeepRecoveryUnavailable('UNKNOWN_STREAM_INFO')
    if pack_pos is None or packed_sizes is None or folders is None:
        raise DeepRecoveryUnavailable('INCOMPLETE_STREAM_METADATA')
    # A supported linear folder always consumes exactly one packed stream.
    if len(packed_sizes) != len(folders):
        raise DeepRecoveryUnavailable('PACKED_FOLDER_COUNT_MISMATCH')
    if sub_counts is None:
        per_folder_sizes = [[block['unpack_sizes'][-1]] for block in folders]
        per_folder_crcs = [[block['folder_crc']] for block in folders]
    assert per_folder_sizes is not None and per_folder_crcs is not None
    blocks: list[dict] = []
    position = pack_pos
    for size, block, subs, crcs in zip(packed_sizes, folders,
                                      per_folder_sizes, per_folder_crcs):
        blocks.append({**block, 'pack_pos': position, 'pack_size': size,
                       'sub_sizes': subs, 'sub_crcs': crcs, 'files': []})
        position += size
    # Keep old single-folder shape for verified encoded-header handling.
    return {**blocks[0], 'blocks': blocks}




def _file_info(p: Parse, stream: dict) -> list[tuple[str, int, int, int | None]]:
    count = p.num()
    if count < 1 or count > 10000:
        raise DeepRecoveryUnavailable('INVALID_FILE_COUNT')
    names: list[str] | None = None
    nonempty = [True] * count
    empty_file_bits: bytes | None = None
    anti_file_bits: bytes | None = None
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
        elif tag == 15:  # kEmptyFile: only the empty-stream entries
            empty_file_bits = sub.raw(len(sub.data) - sub.pos)
        elif tag == 16:  # kAnti: tombstones are never recoverable files
            anti_file_bits = sub.raw(len(sub.data) - sub.pos)
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
    blocks = stream['blocks']
    entries = [(block, length, crc) for block in blocks
               for length, crc in zip(block['sub_sizes'], block['sub_crcs'])]
    if names is None or len(names) != count or sum(nonempty) != len(entries):
        raise DeepRecoveryUnavailable('FILE_MAPPING_UNAVAILABLE')
    empty_count = count - sum(nonempty)
    required_bits = (empty_count + 7) // 8
    if ((empty_file_bits is not None and len(empty_file_bits) != required_bits)
            or (anti_file_bits is not None and len(anti_file_bits) != required_bits)):
        raise DeepRecoveryUnavailable('INVALID_EMPTY_FILE_PROPERTIES')
    manifest: list[tuple[str, int]] = []
    empty_index = 0
    out: list[tuple[str, int, int, int | None]] = []
    positions = {id(block): 0 for block in blocks}
    global_offsets = {}
    total = 0
    for block in blocks:
        global_offsets[id(block)] = total
        total += block['unpack_sizes'][-1]
    n = 0
    for name, present in zip(names, nonempty):
        if not present:
            bit = 0x80 >> (empty_index % 8)
            idx = empty_index // 8
            is_empty_file = empty_file_bits is not None and bool(empty_file_bits[idx] & bit)
            is_anti = anti_file_bits is not None and bool(anti_file_bits[idx] & bit)
            if is_empty_file and not is_anti:
                manifest.append((name, 0))
            empty_index += 1
            continue
        block, length, crc = entries[n]
        manifest.append((name, length))
        key = id(block)
        offset = positions[key]
        block['files'].append((name, offset, length, crc))
        out.append((name, global_offsets[key] + offset, length, crc))
        positions[key] = offset + length
        n += 1
    for block in blocks:
        if positions[id(block)] != block['unpack_sizes'][-1]:
            raise DeepRecoveryUnavailable('UNPACK_SIZES_MISMATCH')
    # Header CRC is verified by the caller before this becomes evidence.
    stream['file_manifest'] = manifest
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


def _header_filter(method: bytes, props: bytes) -> dict:
    """Validate header codec properties before allocating a bounded dictionary."""
    if method == LZMA2_ID:
        return {'id': lzma.FILTER_LZMA2, 'dict_size': _dictionary_size(props)}
    if method != LZMA1_ID:
        raise DeepRecoveryUnavailable('UNSUPPORTED_HEADER_CODER')
    if len(props) != 5 or props[0] >= 225:
        raise DeepRecoveryUnavailable('INVALID_LZMA1_PROPERTIES')
    lc = props[0] % 9
    lp = (props[0] // 9) % 5
    pb = props[0] // 45
    dictionary = int.from_bytes(props[1:], 'little')
    if lc + lp > 4 or dictionary > 32 * 1024**2:
        raise DeepRecoveryUnavailable('UNSUPPORTED_LZMA1_PROPERTIES')
    return {'id': lzma.FILTER_LZMA1, 'dict_size': max(4096, dictionary),
            'lc': lc, 'lp': lp, 'pb': pb}


def _decrypt_header(contents: bytes, props: bytes, size: int, password: str | None) -> bytes:
    """Decrypt metadata in memory, trimming only declared AES block padding."""
    if not password:
        raise DeepRecoveryUnavailable('PASSWORD_REQUIRED')
    if Cipher is None:
        raise DeepRecoveryUnavailable('CRYPTOGRAPHY_NOT_INSTALLED')
    if len(contents) % 16 or not 0 <= len(contents) - size < 16:
        raise DeepRecoveryUnavailable('INVALID_ENCRYPTED_HEADER_SIZE')
    key, iv = _key_and_iv(props, password)
    decoder = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    return (decoder.update(contents) + decoder.finalize())[:size]


def _decode_header(raw: bytes, source: Path, file_size: int, password: str | None = None) -> bytes:
    """Decode bounded LZMA1/LZMA2 and AES metadata; never trust unchecked plaintext."""
    if raw.startswith(b'\x01'):
        return raw
    p = Parse(raw)
    p.tag(23)
    stream = _stream_info(p)
    if len(stream['blocks']) != 1:
        raise DeepRecoveryUnavailable('UNSUPPORTED_7Z_HEADER_CODER_GRAPH')
    coders = stream['coders']
    encrypted = coders[0][0] == AES_ID
    methods = [method for method, _ in coders]
    supported = ([AES_ID], [LZMA1_ID], [LZMA2_ID],
                 [AES_ID, LZMA1_ID], [AES_ID, LZMA2_ID])
    if (p.pos != len(raw) or methods not in supported
            or stream['binds'] != ([(1, 0)] if len(coders) == 2 else [])):
        raise DeepRecoveryUnavailable('UNSUPPORTED_7Z_HEADER_CODER_GRAPH')
    offset = 32 + stream['pack_pos']
    packed = stream['pack_size']
    if (not 0 < packed <= HEADER_LIMIT or offset + packed > file_size
            or any(not 0 < size <= HEADER_LIMIT for size in stream['unpack_sizes'])):
        raise DeepRecoveryUnavailable('INVALID_PACKED_HEADER')
    if stream.get('folder_crc') is None:
        raise DeepRecoveryUnavailable('ENCODED_HEADER_CRC_REQUIRED')
    with source.open('rb') as file:
        file.seek(offset)
        contents = file.read(packed)
    if encrypted:
        contents = _decrypt_header(contents, coders[0][1], stream['unpack_sizes'][0], password)
    out = contents
    method, props = coders[-1]
    if method != AES_ID:
        try:
            dec = lzma.LZMADecompressor(format=lzma.FORMAT_RAW,
                                      filters=[_header_filter(method, props)])
            # LZMA1 without EOS is size-terminated: range-coder flush bytes
            # can decode as extra symbols, so do not request an extra byte.
            limit = stream['unpack_sizes'][-1] + (method == LZMA2_ID)
            out = dec.decompress(contents, max_length=limit)
        except (lzma.LZMAError, ValueError) as exc:
            raise DeepRecoveryUnavailable('INVALID_ENCODED_HEADER') from exc
        # 7-Zip's LZMA1 metadata can omit EOS. Exact size AND decoded CRC
        # verify it; LZMA2 must still contain its mandatory end marker.
        if (method == LZMA2_ID and not dec.eof) or (dec.eof and dec.unused_data):
            raise DeepRecoveryUnavailable('INVALID_ENCODED_HEADER')
    if len(out) != stream['unpack_sizes'][-1]:
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
    blocks: tuple['Metadata', ...] = ()


def _verified_7z_structure(source: Path, password: str | None) -> tuple[dict, list]:
    """Read an original-CRC-verified 7z header independently from payload codecs."""
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
    return _read_header(Parse(_decode_header(raw, source, size, password)))


def verified_7z_inventory(source: Path, password: str | None = None) -> list[tuple[str, int]]:
    """Named regular files from a CRC-verified header; no claim about payload integrity."""
    stream, _ = _verified_7z_structure(source, password)
    return list(stream['file_manifest'])


def inspect_7z(source: Path, password: str | None = None) -> Metadata:
    """Map CRC-bearing files to their own verified independent packed folders."""
    stream, files = _verified_7z_structure(source, password)
    with source.open('rb') as file:
        intro = file.read(32)
    next_offset = struct.unpack('<Q', intro[12:20])[0]
    supported: list[Metadata] = []
    offset_limit = 32 + next_offset
    for block in stream['blocks']:
        coders, binds = block['coders'], block['binds']
        if (len(coders) == 2 and [c[0] for c in coders] == [AES_ID, LZMA2_ID]
                and binds == [(1, 0)]):
            aes_props = coders[0][1]
            lzma_props = coders[1][1]
        elif len(coders) == 1 and coders[0][0] == LZMA2_ID and not binds:
            aes_props = None
            lzma_props = coders[0][1]
        else:
            # A different codec/graph in one folder does not invalidate the
            # trusted locations of independently decodable later folders.
            continue
        dictionary = _dictionary_size(lzma_props)
        packed = block['pack_size']
        offset = 32 + block['pack_pos']
        if (not 0 < packed <= MAX_SCAN_BYTES
                or (aes_props is not None and packed % 16)
                or offset < 32 or offset + packed > offset_limit
                or block['unpack_sizes'][-1] > MAX_SCAN_BYTES):
            raise DeepRecoveryUnavailable('INVALID_LZMA2_PACKED_RANGE')
        supported.append(Metadata(offset, packed, block['unpack_sizes'][-1],
                                  dictionary, aes_props, block['files']))
    if not supported:
        raise DeepRecoveryUnavailable('NOT_AES_OR_PLAIN_LZMA2_LINEAR_FOLDER')
    if not any(crc is not None for block in supported for _, _, _, crc in block.files):
        raise DeepRecoveryUnavailable('NO_PER_FILE_CRCS')
    first = supported[0]
    return Metadata(first.offset, sum(b.packed_size for b in supported),
                    sum(b.unpacked_size for b in supported), first.dictionary,
                    first.aes_props, files, tuple(supported))




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


def _recover_block(source: Path, meta: Metadata, password: str | None, *,
                   check: Callable[[], None],
                   publish: Callable[[str, Iterator[bytes], int, str], bool],
                   attempted: set[str], provenance_prefix: str,
                   scratch_dir: Path | None) -> dict:
    """Incrementally decode a folder; CRC-validate one entire file at a time.

    Memory is bounded by the LZMA2 dictionary, frame, and 2 MiB spool buffer,
    regardless of the folder's uncompressed size. The spool is private and
    discarded before returning; no unverified destination is ever published.
    """
    targets = sorted(((offset, name, size, crc) for name, offset, size, crc in meta.files
                      if crc is not None and size > 0), key=lambda x: x[0])
    cursor = 0
    candidate = None
    candidate_crc = 0
    candidate_written = 0
    recovered = reset_points = segments = rejected = prior = 0
    decoding = False
    dec = None
    reset_origin = 0

    def discard() -> None:
        nonlocal candidate, candidate_written, candidate_crc
        if candidate is not None:
            candidate.close()
        candidate = None
        candidate_written = candidate_crc = 0

    def consume(piece: bytes, at: int) -> None:
        nonlocal cursor, candidate, candidate_written, candidate_crc, recovered
        pos = 0
        while pos < len(piece) and cursor < len(targets):
            check()
            start, name, size, crc = targets[cursor]
            absolute = at + pos
            if start + size <= absolute or name in attempted:
                discard()
                cursor += 1
                continue
            if absolute < start:
                pos += min(len(piece) - pos, start - absolute)
                continue
            # A reset/corruption may have landed in the middle of this file.
            # Never reconstruct an unobserved prefix or guess its CRC.
            if candidate is None:
                if absolute != start:
                    cursor += 1
                    continue
                candidate = tempfile.SpooledTemporaryFile(
                    max_size=2 * 1024 * 1024, mode='w+b', dir=scratch_dir)
            take = min(len(piece) - pos, start + size - absolute)
            block = piece[pos:pos + take]
            candidate.write(block)
            candidate_written += take
            candidate_crc = zlib.crc32(block, candidate_crc)
            pos += take
            if candidate_written == size:
                if candidate_crc == crc:
                    candidate.seek(0)
                    def parts() -> Iterator[bytes]:
                        while True:
                            check()
                            buf = candidate.read(256 * 1024)
                            if not buf:
                                return
                            yield buf
                    if publish(name, parts(), size, f'{provenance_prefix}_reset@{reset_origin}'):
                        recovered += 1
                        attempted.add(name)
                discard()
                cursor += 1

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
                    reset_origin = frame.input_offset
                    segments += 1
                    discard()
                    decoding = True
                    dec = lzma.LZMADecompressor(
                        format=lzma.FORMAT_RAW,
                        filters=[{'id': lzma.FILTER_LZMA2, 'dict_size': meta.dictionary}])
                    while cursor < len(targets) and targets[cursor][0] < frame.output_offset:
                        cursor += 1
                if not decoding:
                    continue
                try:
                    assert dec is not None
                    data = dec.decompress(frame.raw, max_length=frame.decoded_size + 1)
                    if len(data) != frame.decoded_size:
                        raise DeepRecoveryUnavailable('CORRUPTED_LZMA2_CHUNK')
                except (lzma.LZMAError, EOFError, ValueError, DeepRecoveryUnavailable):
                    rejected += 1
                    discard()
                    decoding = False
                    continue
                consume(data, frame.output_offset)
            discard()
            if prior != meta.unpacked_size:
                raise DeepRecoveryUnavailable('UNPACKED_SIZE_MISMATCH')
        except DeepRecoveryUnavailable as exc:
            discard()
            # Framing loss invalidates absolute offsets. The legacy fallback
            # only accepts an entire independent reset segment with exact CRC.
            rescue = _resync_by_full_file_crc(stream, meta, check, publish,
                                               attempted, provenance_prefix=provenance_prefix)
            recovered += rescue['proven_files']
            return {'status': 'framing_resynchronized' if rescue['proven_files'] else 'framing_lost',
                    'reason': str(exc), 'recovered': recovered, 'reset_points': reset_points,
                    'decoded_segments': segments, 'rejected_segments': rejected,
                    'resync_scan': rescue}
        finally:
            discard()
    return {'status': 'completed' if recovered else 'no_proven_files',
            'recovered': recovered, 'reset_points': reset_points,
            'decoded_segments': segments, 'rejected_segments': rejected}


def recover_aes_lzma2(source: Path, password: str | None, *, check: Callable[[], None],
                       publish: Callable[[str, Iterator[bytes], int, str], bool],
                       scratch_dir: Path | None = None) -> dict:
    """Salvage independent 7z folders, publishing only full CRC-matching files."""
    meta = inspect_7z(source, password)
    blocks = meta.blocks or (meta,)
    attempted: set[str] = set()
    totals = {'recovered': 0, 'reset_points': 0, 'decoded_segments': 0,
              'rejected_segments': 0}
    results = []
    for index, block in enumerate(blocks):
        check()
        prefix = '7z_aes_lzma2' if block.aes_props is not None else '7z_lzma2'
        result = _recover_block(
            source, block, password, check=check, publish=publish,
            attempted=attempted, provenance_prefix=prefix,
            scratch_dir=scratch_dir)
        results.append(result)
        for key in totals:
            totals[key] += result[key]
    modes = {b.aes_props is not None for b in blocks}
    stream_mode = ('aes_lzma2' if modes == {True}
                   else 'plain_lzma2' if modes == {False} else 'mixed_lzma2')
    if any(r['status'] == 'framing_resynchronized' for r in results):
        status = 'framing_resynchronized'
    elif any(r['status'] == 'framing_lost' for r in results):
        status = 'partial' if totals['recovered'] else 'framing_lost'
    else:
        status = 'completed' if totals['recovered'] else 'no_proven_files'
    summary = {'status': status, 'stream_mode': stream_mode,
               'folders': len(blocks), 'folder_results': results, **totals}
    # Existing single-folder callers consume this top-level diagnostic.
    # Multi-folder reports retain each folder's independent scan details.
    if len(results) == 1:
        for field in ('reason', 'resync_scan'):
            if field in results[0]:
                summary[field] = results[0][field]
    return summary




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
