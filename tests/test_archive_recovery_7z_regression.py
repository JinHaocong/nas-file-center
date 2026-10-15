"""Regression: damaged unencrypted 7z LZMA2 can still contain CRC-proven reset files.

Synthetic bytes only; no production archive or NAS access.
"""
from __future__ import annotations

import json
import lzma
import os
from pathlib import Path
from types import SimpleNamespace
import struct
import zlib

import pytest

from app.archive_recovery import core, integration
from app.archive_recovery.aes_lzma2 import inspect_7z


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
