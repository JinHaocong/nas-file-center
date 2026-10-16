"""Multi-folder 7z and large solid decode regressions.

All test payloads are synthetic; original archive files are never overwritten.
"""
from __future__ import annotations

import lzma
import os
from pathlib import Path
import struct
import zlib

import pytest
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from app.archive_recovery import core
from app.archive_recovery.aes_lzma2 import (
    DeepRecoveryUnavailable, _key_and_iv, inspect_7z, recover_aes_lzma2,
)


def _num(n: int) -> bytes:
    for extra in range(8):
        if n < (1 << (7 * (extra + 1))):
            head = ((0xff << (8 - extra)) & 0xff) | (n >> (8 * extra))
            return bytes([head]) + (n & ((1 << (8 * extra)) - 1)).to_bytes(extra, "little")
    return b"\xff" + n.to_bytes(8, "little")


def _pack(payload: bytes, *, aes: bool) -> tuple[bytes, int]:
    compressor = lzma.LZMACompressor(format=lzma.FORMAT_RAW, filters=[
        {"id": lzma.FILTER_LZMA2, "dict_size": 1 << 20},
    ])
    raw = compressor.compress(payload) + compressor.flush()
    if not aes:
        return raw, len(raw)
    key, iv = _key_and_iv(b"\x3f", "fixture-password")
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    padded = raw + bytes((-len(raw)) % 16)
    return cipher.update(padded) + cipher.finalize(), len(raw)


def _write_archive(path: Path, groups: list[list[tuple[str, bytes]]], *,
                   aes: bool = False, damage_folder: int | None = None) -> None:
    """Encode independent folders, their per-folder substreams and CRCs."""
    payloads = [b"".join(blob for _, blob in group) for group in groups]
    packs = [_pack(blob, aes=aes) for blob in payloads]
    pack_bytes = [p[0] for p in packs]
    if damage_folder is not None:
        damaged = bytearray(pack_bytes[damage_folder])
        # Damage the compression stream without changing its length/header.
        damaged[min(32, len(damaged) - 2)] ^= 0x40
        pack_bytes[damage_folder] = bytes(damaged)
    all_packed = b"".join(pack_bytes)

    streams = b"\x06" + _num(0) + _num(len(groups)) + b"\x09"
    streams += b"".join(_num(len(p)) for p in pack_bytes) + b"\x00"
    streams += b"\x07\x0b" + _num(len(groups)) + b"\x00"
    for group in groups:
        if aes:
            streams += b"\x02\x24\x06\xf1\x07\x01\x01\x3f"
        else:
            streams += b"\x01"
        streams += b"\x21\x21\x01\x10"
        if aes:
            streams += b"\x01\x00"  # AES output binds LZMA2 input
    streams += b"\x0c"
    for (packed, raw_size), payload in zip(packs, payloads):
        if aes:
            streams += _num(raw_size)
        streams += _num(len(payload))
    streams += b"\x00"

    streams += b"\x08\x0d" + b"".join(_num(len(g)) for g in groups)
    streams += b"\x09"
    for group in groups:
        streams += b"".join(_num(len(blob)) for _, blob in group[:-1])
    streams += b"\x0a\x01" + b"".join(
        struct.pack("<I", zlib.crc32(blob)) for group in groups for _, blob in group
    )
    streams += b"\x00\x00"
    files = [entry for group in groups for entry in group]
    names = ("\0".join(name for name, _ in files) + "\0").encode("utf-16-le")
    file_info = b"\x05" + _num(len(files)) + b"\x11" + _num(len(names) + 1) + b"\0" + names + b"\0"
    header = b"\x01\x04" + streams + file_info + b"\0"
    start = struct.pack("<QQI", len(all_packed), len(header), zlib.crc32(header))
    signature = b"7z\xbc\xaf\x27\x1c\x00\x04" + struct.pack("<I", zlib.crc32(start))
    path.write_bytes(signature + start + all_packed + header)


@pytest.mark.parametrize("aes", [False, True])
def test_two_packed_folders_are_independently_recovered(tmp_path, aes):
    first = os.urandom(7000)
    second = os.urandom(9000)
    source = tmp_path / "two-folders.7z"
    _write_archive(source, [[("first.bin", first)], [("second.bin", second)]], aes=aes)
    before = source.read_bytes()
    metadata = inspect_7z(source, "fixture-password" if aes else None)
    assert len(metadata.blocks) == 2
    output = {}
    result = recover_aes_lzma2(
        source, "fixture-password" if aes else None,
        check=lambda: None,
        publish=lambda name, chunks, length, prov: output.setdefault(name, b"".join(chunks)) is not None,
    )
    assert output == {"first.bin": first, "second.bin": second}
    assert result["recovered"] == 2
    assert source.read_bytes() == before


def test_substream_boundaries_restart_for_each_folder(tmp_path):
    files = [[("a.bin", b"a" * 1500), ("b.bin", b"b" * 2200)],
             [("c.bin", b"c" * 3400)]]
    source = tmp_path / "substreams.7z"
    _write_archive(source, files)
    output = {}
    result = recover_aes_lzma2(
        source, None, check=lambda: None,
        publish=lambda name, chunks, length, prov: output.setdefault(name, b"".join(chunks)) is not None,
    )
    assert output == dict(files[0] + files[1])
    assert result["recovered"] == 3


def test_corrupted_first_folder_does_not_block_second(tmp_path, monkeypatch):
    first, second = os.urandom(8000), os.urandom(9000)
    source = tmp_path / "damaged.7z"
    _write_archive(source, [[("damaged.bin", first)], [("good.bin", second)]],
                   aes=True, damage_folder=0)
    output = tmp_path / "output"
    output.mkdir()
    monkeypatch.setattr(core, "_libarchive", lambda *args: (_ for _ in ()).throw(
        core.RecoveryError("DAMAGED_ARCHIVE")))
    report = core.recover_archive(source, output, password="fixture-password", deep=True)
    assert (output / "good.bin").read_bytes() == second
    assert not (output / "damaged.bin").exists()
    assert report["stats"]["integrity_passed"] == 1
    assert not list(output.rglob(".nfc-part-*"))


def test_large_solid_stream_recovers_trailing_small_file_with_bounded_memory(tmp_path, monkeypatch):
    from app.archive_recovery import aes_lzma2

    large = b"A" * (33 * 1024 * 1024)
    small = b"last small file" * 1000
    source = tmp_path / "large-solid.7z"
    _write_archive(source, [[("big.bin", large), ("small.bin", small)]])
    # Intact streaming must not decode a whole solid segment into one bytearray.
    monkeypatch.setattr(aes_lzma2, "_decode_segment", lambda *args: pytest.fail(
        "healthy stream must not use whole-segment decode"))
    found = {}
    result = recover_aes_lzma2(
        source, None, check=lambda: None,
        publish=lambda name, chunks, length, prov: found.setdefault(name, b"".join(chunks)) is not None,
        scratch_dir=tmp_path,
    )
    assert found["big.bin"] == large
    assert found["small.bin"] == small
    assert result["recovered"] == 2
    assert sorted(p.name for p in tmp_path.iterdir()) == ["large-solid.7z"]
