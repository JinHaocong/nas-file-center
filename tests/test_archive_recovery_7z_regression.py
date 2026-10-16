"""Regression: damaged unencrypted 7z LZMA2 can still contain CRC-proven reset files.

Synthetic bytes only; no production archive or NAS access.
"""
from __future__ import annotations

import json
import lzma
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
import struct
import zlib

import pytest
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from app.archive_recovery import core, integration
from app.archive_recovery.aes_lzma2 import DeepRecoveryUnavailable, inspect_7z, recover_aes_lzma2


@pytest.mark.parametrize("encrypted", [False, True])
@pytest.mark.parametrize("file_count", [1, 10])
def test_real_7zip_default_header_can_be_recovered(tmp_path, encrypted, file_count):
    """Catch default LZMA1 / AES metadata being rejected before payload scanning."""
    binary = shutil.which("7zz") or shutil.which("7z")
    if not binary:
        pytest.skip("7-Zip executable is not installed")
    payload = b"actual 7-Zip header regression\n" * 1000
    expected = {f"课程_{i:03}.txt": payload for i in range(file_count)}
    for name, content in expected.items():
        (tmp_path / name).write_bytes(content)
    source = tmp_path / "real.7z"
    args = [binary, "a", str(source), *expected, "-m0=LZMA2", "-md=1m"]
    if encrypted:
        args += ["-psynthetic-test-password", "-mhe=on"]
    subprocess.run(args, cwd=tmp_path, check=True, capture_output=True)
    published = {}

    def publish(name, chunks, size, provenance):
        published[name] = b"".join(chunks)
        return True

    result = recover_aes_lzma2(
        source, "synthetic-test-password" if encrypted else None,
        check=lambda: None, publish=publish,
    )
    assert published == expected
    assert result["recovered"] == file_count


def _num(n: int) -> bytes:
    for extra in range(8):
        if n < (1 << (7 * (extra + 1))):
            first = ((0xff << (8 - extra)) & 0xff) | (n >> (8 * extra))
            return bytes([first]) + (n & ((1 << (8 * extra)) - 1)).to_bytes(extra, "little")
    return b"\xff" + n.to_bytes(8, "little")


def _chunk(data: bytes) -> bytes:
    compressor = lzma.LZMACompressor(format=lzma.FORMAT_RAW, filters=[
        {"id": lzma.FILTER_LZMA2, "dict_size": 1 << 20}
    ])
    raw = compressor.compress(data) + compressor.flush()
    assert raw[-1:] == b"\0"
    assert raw[0] == 1 or raw[0] >= 0xe0
    return raw


def _plain_7z(path: Path, first: bytes, second: bytes) -> None:
    # Independent dictionary-reset LZMA2 segments, accurately described by
    # the verified 7z header (name/size/CRC); damage is only in packed data.
    a, b = _chunk(first), _chunk(second)
    packed = a[:-1] + b
    streams = b"\x06" + _num(0) + _num(1) + b"\x09" + _num(len(packed)) + b"\0"
    streams += b"\x07\x0b" + _num(1) + b"\0" + _num(1)
    streams += b"\x21\x21" + _num(1) + b"\x10"
    streams += b"\x0c" + _num(len(first) + len(second)) + b"\0"
    streams += b"\x08\x0d" + _num(2) + b"\x09" + _num(len(first))
    streams += b"\x0a\x01" + struct.pack("<II", zlib.crc32(first), zlib.crc32(second))
    streams += b"\0\0"
    names = "broken.bin\0可恢复.bin\0".encode("utf-16-le")
    files = b"\x05" + _num(2) + b"\x11" + _num(len(names) + 1) + b"\0" + names + b"\0"
    header = b"\x01\x04" + streams + files + b"\0"
    start = struct.pack("<QQI", len(packed), len(header), zlib.crc32(header))
    signature = b"7z\xbc\xaf\x27\x1c\x00\x04" + struct.pack("<I", zlib.crc32(start))
    contents = bytearray(signature + start + packed + header)
    # Corrupt compressed bytes in the first segment, not any metadata.
    contents[32 + 140] ^= 0x40
    path.write_bytes(contents)


def _encode_metadata(path, codec="lzma1", encrypted=False, crc_mode="valid", oversize=False):
    """Wrap a damaged-data fixture's intact metadata in a standard encoded header."""
    original = path.read_bytes()
    offset, size, _ = struct.unpack("<QQI", original[12:32])
    header = original[32 + offset:32 + offset + size]
    packed = header
    coders = b""
    sizes = []
    if codec != "none":
        filter_id = lzma.FILTER_LZMA1 if codec == "lzma1" else lzma.FILTER_LZMA2
        packed = lzma.compress(header, format=lzma.FORMAT_RAW,
                               filters=[{"id": filter_id, "dict_size": 1 << 20}])
        coders = (b"\x23\x03\x01\x01\x05\x5d\x00\x00\x10\x00"
                  if codec == "lzma1" else b"\x21\x21\x01\x10")
        sizes = [len(header)]
    if encrypted:
        # 7z's special no-hash KDF: password UTF-16LE, zero-padded to 32 bytes.
        key = "fixture".encode("utf-16-le").ljust(32, b"\0")
        encoder = Cipher(algorithms.AES(key), modes.CBC(bytes(16))).encryptor()
        sizes.insert(0, len(packed))
        packed = encoder.update(packed + bytes((-len(packed)) % 16)) + encoder.finalize()
        coders = b"\x24\x06\xf1\x07\x01\x01\x3f" + coders
    count = len(sizes)
    if oversize:
        sizes[-1] = 17 * 1024 * 1024
    streams = b"\x06" + _num(offset) + b"\x01\x09" + _num(len(packed)) + b"\0"
    streams += b"\x07\x0b\x01\0" + _num(count) + coders
    if count == 2:
        streams += b"\x01\0"
    streams += b"\x0c" + b"".join(_num(n) for n in sizes)
    if crc_mode != "missing":
        crc = zlib.crc32(header) ^ (1 if crc_mode == "wrong" else 0)
        streams += b"\x0a\x01" + struct.pack("<I", crc)
    next_header = b"\x17" + streams + b"\0\0"
    payload = original[32:32 + offset] + packed
    start = struct.pack("<QQI", len(payload), len(next_header), zlib.crc32(next_header))
    path.write_bytes(original[:8] + struct.pack("<I", zlib.crc32(start)) + start + payload + next_header)


@pytest.mark.parametrize("codec,encrypted", [
    ("lzma1", False), ("lzma2", False), ("none", True),
    ("lzma1", True), ("lzma2", True),
])
def test_encoded_header_salvages_crc_verified_file_after_damage(tmp_path, monkeypatch, codec, encrypted):
    source = tmp_path / "damaged.7z"
    second = os.urandom(9000)
    _plain_7z(source, os.urandom(8000), second)
    _encode_metadata(source, codec, encrypted)
    before = source.read_bytes()
    output = tmp_path / "result"
    output.mkdir()
    monkeypatch.setattr(core, "_libarchive",
                        lambda *args: (_ for _ in ()).throw(core.RecoveryError("DAMAGED_ARCHIVE")))
    report = core.recover_archive(source, output, password="fixture" if encrypted else None, deep=True)
    assert (output / "可恢复.bin").read_bytes() == second
    assert not (output / "broken.bin").exists()
    assert report["stats"]["integrity_passed"] == 1
    assert source.read_bytes() == before


@pytest.mark.parametrize("codec", ["none", "lzma1", "lzma2"])
@pytest.mark.parametrize("password", [None, "incorrect"])
def test_encrypted_header_without_correct_password_never_publishes(tmp_path, codec, password):
    source = tmp_path / "encrypted.7z"
    _plain_7z(source, os.urandom(8000), os.urandom(9000))
    _encode_metadata(source, codec, True)
    published = []
    with pytest.raises(DeepRecoveryUnavailable) as error:
        recover_aes_lzma2(source, password, check=lambda: None,
                          publish=lambda *args: published.append(args))
    if password is None:
        assert str(error.value) == "PASSWORD_REQUIRED"
    assert not published


@pytest.mark.parametrize("crc_mode,oversize,reason", [
    ("wrong", False, "ENCODED_HEADER_CRC_MISMATCH"),
    ("missing", False, "ENCODED_HEADER_CRC_REQUIRED"),
    ("valid", True, "INVALID_PACKED_HEADER"),
])
def test_encoded_header_rejects_unverified_or_oversized_metadata(tmp_path, crc_mode, oversize, reason):
    source = tmp_path / "invalid.7z"
    _plain_7z(source, os.urandom(8000), os.urandom(9000))
    _encode_metadata(source, crc_mode=crc_mode, oversize=oversize)
    with pytest.raises(DeepRecoveryUnavailable, match=reason):
        inspect_7z(source)


def test_plain_7z_deep_salvages_later_crc_reset_without_password(tmp_path, monkeypatch):
    source = tmp_path / "课件_044.7z"
    first, second = os.urandom(8000), os.urandom(9000)
    _plain_7z(source, first, second)
    out = tmp_path / "recover"
    out.mkdir()
    monkeypatch.setattr(core, "_libarchive",
                        lambda *args: (_ for _ in ()).throw(core.RecoveryError("DAMAGED_ARCHIVE")))
    report = core.recover_archive(source, out, deep=True)
    assert (out / "可恢复.bin").read_bytes() == second
    assert not (out / "broken.bin").exists()
    assert report["stats"]["integrity_passed"] == 1
    assert report["aes_lzma2_deep"]["recovered"] >= 1
    assert report["aes_lzma2_deep"]["status"] in {"completed", "framing_resynchronized"}


def test_plain_7z_has_metadata_without_password(tmp_path):
    source = tmp_path / "plain.7z"
    _plain_7z(source, os.urandom(8000), os.urandom(9000))
    metadata = inspect_7z(source)
    assert metadata.files[1][0] == "可恢复.bin"
    assert metadata.aes_props is None


def test_no_files_report_retains_deep_unsupported_reason(tmp_path, monkeypatch):
    source = tmp_path / "broken.7z"
    source.write_bytes(b"7z\xbc\xaf\x27\x1c" + b"x" * 40)
    output = tmp_path / "broken.7z_恢复结果_test"
    output.mkdir()
    observed = source.stat()
    outstat = output.stat()
    settings = SimpleNamespace(
        allow_mutation=True, allowed_roots=[str(tmp_path)],
        quarantine_root=tmp_path / ".trash", config_dir=tmp_path / "config"
    )
    job = SimpleNamespace(id=9001, state_json=json.dumps({
        "source": str(source), "output": str(output), "deep": True,
        "identity": list(map(str, [observed.st_dev, observed.st_ino, observed.st_size, observed.st_mtime_ns])),
        "output_identity": list(map(str, [outstat.st_dev, outstat.st_ino])),
    }))
    context = SimpleNamespace(checkpoint=lambda **kwargs: None)
    def no_files(*args, **kwargs):
        kwargs["items"].append({"name": "<archive>", "status": "unrecovered", "reason": "PASSWORD_OR_DATA_ERROR"})
        return {
            "format": "7z", "known_total": None,
            "deep_capability": "aes_lzma2_crc_reset",
            "aes_lzma2_deep": {"status": "unsupported", "reason": "ENCRYPTED_OR_COMPLEX_7Z_HEADER", "recovered": 0},
            "warnings": ["Only verified payloads can be published."],
        }
    monkeypatch.setattr(integration, "recover_archive", no_files)
    with pytest.raises(core.RecoveryError, match="NO_FILES_RECOVERED"):
        integration.ArchiveRecoveryHandler().run(job, context, settings)
    report = json.loads(integration.report_path(settings, job.id).read_text())
    assert report["recovery_status"] == "failed"
    assert report["error_code"] == "NO_FILES_RECOVERED"
    assert report["aes_lzma2_deep"]["reason"] == "ENCRYPTED_OR_COMPLEX_7Z_HEADER"
    assert report["deep_capability"] == "aes_lzma2_crc_reset"
    assert len(report["items"]) == 1
    assert source.exists()



@pytest.mark.parametrize("reason", ["RESOURCE_LIMIT", "TIME_LIMIT", "INVALID_SOURCE_OR_DESTINATION"])
def test_7z_deep_does_not_override_safety_failures(tmp_path, monkeypatch, reason):
    source = tmp_path / "limited.7z"
    _plain_7z(source, os.urandom(8000), os.urandom(9000))
    out = tmp_path / "recover"
    out.mkdir()

    def blocked(*args):
        raise core.RecoveryError(reason)

    monkeypatch.setattr(core, "_libarchive", blocked)
    with pytest.raises(core.RecoveryError, match=reason):
        core.recover_archive(source, out, deep=True)
    assert not (out / "可恢复.bin").exists()
    assert source.exists()
