"""Synthetic archive fixtures only: never use private NAS content."""
from __future__ import annotations

import io
from pathlib import Path
import tarfile
import zipfile

import pytest
from PIL import Image

from app.archive_recovery.core import RecoveryError, detect_format, recover_archive, safe_parts


def result(tmp_path: Path, source: Path, **kwargs):
    dst = tmp_path / ('result' + str(len(list(tmp_path.glob('result*')))))
    dst.mkdir()
    return recover_archive(source, dst, **kwargs), dst


def test_clean_zip_with_unicode_and_spaces(tmp_path):
    source = tmp_path / 'a.zip'
    with zipfile.ZipFile(source, 'w') as z:
        z.writestr('中文 目录/hello world.txt', 'hello')
    report, dst = result(tmp_path, source)
    assert report['known_total'] == 1
    assert report['stats']['integrity_passed'] == 1
    assert (dst / '中文 目录' / 'hello world.txt').read_text() == 'hello'
    assert list(dst.glob('.nfc*')) == []


def test_broken_zip_central_directory_salvages_local_headers(tmp_path):
    source = tmp_path / 'a.zip'
    with zipfile.ZipFile(source, 'w') as z:
        z.writestr('survivor.txt', 'clean')
    source.write_bytes(source.read_bytes()[:-19])
    report, dst = result(tmp_path, source)
    assert report['known_total'] is None
    assert report['items'][0]['provenance'] == 'zip_local_header'
    assert report['stats']['integrity_passed'] == 1
    assert (dst / 'survivor.txt').read_text() == 'clean'


def test_zip_partial_crc_does_not_count_as_integrity_passed(tmp_path):
    source = tmp_path / 'a.zip'
    with zipfile.ZipFile(source, 'w', compression=zipfile.ZIP_STORED) as z:
        z.writestr('bad.txt', 'payload')
    blob = source.read_bytes().replace(b'payload', b'payloXd', 1)
    source.write_bytes(blob)
    report, dst = result(tmp_path, source)
    assert report['stats']['integrity_passed'] == 0
    assert report['stats']['incomplete'] == 1
    assert not (dst / 'bad.txt').exists()
    assert len(list((dst / '_incomplete').iterdir())) == 1


def test_fake_tar_header_and_symlinks_are_not_extracted(tmp_path):
    source = tmp_path / 'a.tar'
    with tarfile.open(source, 'w') as tar:
        block = b'hello'
        ti = tarfile.TarInfo('safe/ok.txt')
        ti.size = len(block)
        tar.addfile(ti, io.BytesIO(block))
        link = tarfile.TarInfo('safe/evil')
        link.type = tarfile.SYMTYPE
        link.linkname = '../../escape'
        tar.addfile(link)
    report, dst = result(tmp_path, source)
    assert (dst / 'safe/ok.txt').read_bytes() == b'hello'
    assert not (dst / 'safe/evil').exists()
    assert report['stats']['unverified'] == 1
    assert report['stats']['unrecovered'] == 1


def test_tar_header_corruption_resynchronizes_without_claiming_crc(tmp_path):
    source = tmp_path / 'a.tar'
    with tarfile.open(source, 'w') as tar:
        for name in ['a.txt', 'b.txt']:
            payload = name.encode()
            ti = tarfile.TarInfo(name)
            ti.size = len(payload)
            tar.addfile(ti, io.BytesIO(payload))
    blob = bytearray(source.read_bytes())
    blob[148] = ord('z')
    source.write_bytes(blob)
    report, dst = result(tmp_path, source)
    assert not (dst / 'a.txt').exists()
    assert (dst / 'b.txt').read_text() == 'b.txt'
    assert report['stats']['integrity_passed'] == 0


def test_tar_truncated_item_is_separated(tmp_path):
    source = tmp_path / 'a.tar'
    with tarfile.open(source, 'w') as tar:
        payload = b'abcdefghij'
        ti = tarfile.TarInfo('long.txt')
        ti.size = 10
        tar.addfile(ti, io.BytesIO(payload))
    source.write_bytes(source.read_bytes()[:517])
    report, dst = result(tmp_path, source)
    assert report['stats']['incomplete'] == 1
    assert not (dst / 'long.txt').exists()


@pytest.mark.parametrize('name', ['../escape', '/tmp/x', r'..\\outside', 'C:/outside', '_incomplete/x', 'a/../b'])
def test_unsafe_names_rejected(name):
    with pytest.raises(RecoveryError, match='UNSAFE_PATH'):
        safe_parts(name)


def test_broken_image_not_reported_format_validated(tmp_path):
    source = tmp_path / 'a.tar'
    with tarfile.open(source, 'w') as tar:
        payload = b'\xff\xd8\xff\x00\x00BADJPEG'
        ti = tarfile.TarInfo('bad.jpg')
        ti.size = len(payload)
        tar.addfile(ti, io.BytesIO(payload))
    report, dst = result(tmp_path, source)
    assert report['stats']['format_validated'] == 0
    assert report['stats']['incomplete'] == 1


def test_valid_image_format_verified_not_crc(tmp_path):
    payload = io.BytesIO()
    Image.new('RGB', (3, 3)).save(payload, format='JPEG')
    source = tmp_path / 'a.tar'
    with tarfile.open(source, 'w') as tar:
        ti = tarfile.TarInfo('ok.jpg')
        ti.size = len(payload.getvalue())
        tar.addfile(ti, io.BytesIO(payload.getvalue()))
    report, _ = result(tmp_path, source)
    assert report['stats']['format_validated'] == 1
    assert report['stats']['integrity_passed'] == 0


def test_limits_and_no_existing_output_overwrite(tmp_path, monkeypatch):
    source = tmp_path / 'a.zip'
    with zipfile.ZipFile(source, 'w') as z:
        z.writestr('x', 'abcdefghij')
    dst = tmp_path / 'result'
    dst.mkdir()
    (dst / 'keep').write_text('original')
    with pytest.raises(RecoveryError, match='DESTINATION_NOT_EMPTY'):
        recover_archive(source, dst)
    assert (dst / 'keep').read_text() == 'original'
    import app.archive_recovery.core as core
    monkeypatch.setattr(core, 'MAX_BYTES', 3)
    with pytest.raises(RecoveryError, match='RESOURCE_LIMIT'):
        result(tmp_path, source)


def test_password_not_logged_in_error_or_report(tmp_path):
    source = tmp_path / 'a.zip'
    with zipfile.ZipFile(source, 'w') as z:
        z.writestr('plain.txt', 'text')
    report, dst = result(tmp_path, source, password='secret-sentinel')
    assert 'secret-sentinel' not in str(report)
    assert (dst / 'plain.txt').exists()