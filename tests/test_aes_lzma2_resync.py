"""Small hand-built 7z fixtures: independent LZMA2 reset chunks, AES-256 CBC.

Fixtures encode documented 7z folder graph, CRC and filename metadata without
third-party archive writers. Passwords and ciphertext are synthetic.
"""
from __future__ import annotations

import os
from pathlib import Path
import struct
import zlib
import lzma

import pytest
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from app.archive_recovery.aes_lzma2 import (
    DeepRecoveryUnavailable, inspect_7z, _key_and_iv, recover_aes_lzma2
)


def num(n: int) -> bytes:
    if n < 0:
        raise ValueError()
    for extra in range(8):
        if n < (1 << (7 * (extra + 1))):
            first = ((0xff << (8 - extra)) & 0xff) | (n >> (8 * extra))
            return bytes([first]) + (n & ((1 << (8 * extra)) - 1)).to_bytes(extra, 'little')
    return b'\xff' + n.to_bytes(8, 'little')


def raw_chunk(blob: bytes) -> bytes:
    compressor = lzma.LZMACompressor(format=lzma.FORMAT_RAW, filters=[
        {'id': lzma.FILTER_LZMA2, 'dict_size': 1 << 20}
    ])
    out = compressor.compress(blob) + compressor.flush()
    assert out.endswith(b'\0')
    assert out[0] in (1, *range(0xe0, 0x100))
    return out


def build_7z(path: Path, payloads: tuple[bytes, bytes], *, password='good',
             encoded_header=False, with_crc=True, corrupt_block=None,
             names=('bad.bin', 'recovered.bin'), aes_props=b'\x3f') -> None:
    # Join two independently compressed LZMA2 streams. Both streams begin
    # with a dictionary reset, while the first EOS marker is omitted.
    first, second = map(raw_chunk, payloads)
    packed_raw = first[:-1] + second
    padding = (-len(packed_raw)) % 16
    plaintext = packed_raw + bytes(padding)
    key, iv = _key_and_iv(aes_props, password)
    enc = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    ciphertext = bytearray(enc.update(plaintext) + enc.finalize())
    if corrupt_block is not None:
        assert corrupt_block + 16 < len(first)
        ciphertext[corrupt_block] ^= 0x40
    pack_size = len(ciphertext)
    streams = b'\x06' + num(0) + num(1) + b'\x09' + num(pack_size) + b'\x00'
    # AES (coder0) feeds LZMA2 (coder1), bind index (in=1,out=0)
    streams += b'\x07\x0b' + num(1) + b'\x00' + num(2)
    streams += b'\x24\x06\xf1\x07\x01' + num(len(aes_props)) + aes_props
    streams += b'\x21\x21' + num(1) + b'\x10'
    streams += num(1) + num(0) + b'\x0c' + num(pack_size) + num(sum(map(len,payloads))) + b'\x00'
    streams += b'\x08\x0d' + num(2) + b'\x09' + num(len(payloads[0]))
    if with_crc:
        streams += b'\x0a\x01' + b''.join(struct.pack('<I',zlib.crc32(x)) for x in payloads)
    streams += b'\x00\x00'
    names = ('\0'.join(names) + '\0').encode('utf-16-le')
    files = b'\x05' + num(2) + b'\x11' + num(len(names)+1) + b'\0' + names + b'\0'
    header = b'\x01\x04' + streams + files + b'\x00'
    if encoded_header:
        c = lzma.LZMACompressor(format=lzma.FORMAT_RAW, filters=[
            {'id':lzma.FILTER_LZMA2,'dict_size':1<<20}])
        packed_header = c.compress(header) + c.flush()
        header_stream = (b'\x06' + num(pack_size) + num(1) + b'\x09' + num(len(packed_header)) + b'\0'
                         + b'\x07\x0b' + num(1) + b'\0' + num(1)
                         + b'\x21\x21' + num(1) + b'\x10'
                         + b'\x0c' + num(len(header)) + b'\x0a\x01'
                         + struct.pack('<I', zlib.crc32(header)) + b'\0\0')
        next_header = b'\x17' + header_stream
        payload_end = bytes(ciphertext) + packed_header
    else:
        next_header = header
        payload_end = bytes(ciphertext)
    start_header = struct.pack('<QQI', len(payload_end), len(next_header), zlib.crc32(next_header))
    sig = b'7z\xbc\xaf\x27\x1c\x00\x04' + struct.pack('<I',zlib.crc32(start_header)) + start_header
    path.write_bytes(sig + payload_end + next_header)


@pytest.mark.parametrize('encoded',[False, True])
def test_salvage_after_corrupt_aes_block(tmp_path: Path, encoded: bool):
    a = os.urandom(8000)
    b = os.urandom(9000)
    source = tmp_path / 'example.7z'
    build_7z(source, (a, b), encoded_header=encoded, corrupt_block=160)
    meta = inspect_7z(source)
    assert len(meta.files) == 2
    out = {}
    def publish(name, chunks, size, provenance):
        data = b''.join(chunks)
        assert len(data) == size and provenance.startswith('7z_aes_lzma2_reset@')
        out[name] = data
        return True
    report = recover_aes_lzma2(source, 'good', check=lambda: None, publish=publish)
    assert out == {'recovered.bin':b}
    assert report['recovered'] == 1
    assert report['reset_points'] >= 2


def test_intact_aes_lzma2_can_prove_both(tmp_path: Path):
    a, b = os.urandom(4000), os.urandom(6000)
    source = tmp_path / 'full.7z'
    build_7z(source, (a,b))
    outputs = {}
    def publish(name, chunks, size, origin):
        outputs[name] = b''.join(chunks)
        return True
    result = recover_aes_lzma2(source, 'good', check=lambda:None, publish=publish)
    assert outputs == {'bad.bin':a,'recovered.bin':b}
    assert result['recovered'] == 2


def test_wrong_password_never_publishes(tmp_path: Path):
    source = tmp_path / 'wrong.7z'
    build_7z(source, (os.urandom(4000),os.urandom(3000)))
    outputs=[]
    result=recover_aes_lzma2(source,'wrong',check=lambda:None,
         publish=lambda *a: outputs.append(a) or True)
    assert not outputs
    assert result['recovered'] == 0


def test_missing_crc_is_explicitly_unsupported(tmp_path: Path):
    source=tmp_path/'no-crc.7z'
    build_7z(source,(b'x'*5000,b'y'*5000),with_crc=False)
    with pytest.raises(DeepRecoveryUnavailable,match='NO_PER_FILE_CRCS'):
        inspect_7z(source)


def test_tampered_header_is_rejected(tmp_path: Path):
    source=tmp_path/'header.7z'
    build_7z(source,(b'a'*4000,b'b'*4000))
    data=bytearray(source.read_bytes());data[-1]^=1;source.write_bytes(data)
    with pytest.raises(DeepRecoveryUnavailable,match='NEXT_HEADER_CRC_MISMATCH'):
        inspect_7z(source)


def test_kdf_properties_reject_high_cost():
    with pytest.raises(DeepRecoveryUnavailable,match='AES_KDF_TOO_EXPENSIVE'):
        _key_and_iv(b'\x20','pass')


def test_recover_archive_integration_with_unavailable_normal_reader(tmp_path: Path, monkeypatch):
    from app.archive_recovery import core
    a, b = os.urandom(8000), os.urandom(9500)
    source = tmp_path / 'input.7z'
    out = tmp_path / 'input_恢复结果'
    out.mkdir()
    build_7z(source, (a,b), corrupt_block=160)
    def unavailable(*args, **kwargs):
        raise core.RecoveryError('STANDARD_READER_FAILED')
    monkeypatch.setattr(core, '_libarchive', unavailable)
    report = core.recover_archive(source, out, password='good', deep=True)
    assert (out/'recovered.bin').read_bytes() == b
    assert not (out/'bad.bin').exists()
    assert not list(out.rglob('.nfc-part-*'))
    assert report['aes_lzma2_deep']['recovered'] == 1
    assert report['stats']['integrity_passed'] == 1


def test_recover_archive_deep_flag_off_does_not_bypass_reader_failure(tmp_path: Path, monkeypatch):
    from app.archive_recovery import core
    source = tmp_path / 'input.7z'
    out = tmp_path / 'result'
    out.mkdir()
    build_7z(source, (b'a'*1000, b'b'*1000))
    def unavailable(*args, **kwargs):
        raise core.RecoveryError('STANDARD_READER_FAILED')
    monkeypatch.setattr(core, '_libarchive', unavailable)
    with pytest.raises(core.RecoveryError,match='STANDARD_READER_FAILED'):
        core.recover_archive(source,out,password='good',deep=False)


def test_resync_after_destroyed_first_lzma2_header(tmp_path: Path):
    # Destroy encrypted first block (the LZMA2 control header). Missing
    # uncompressed offset cannot be inferred from damaged framing; whole-file
    # original CRC matching is the only safe way to identify the next file.
    from app.archive_recovery.aes_lzma2 import _key_and_iv, DecryptedStream, inspect_7z
    a, b = os.urandom(8000), os.urandom(9000)
    source=tmp_path/'broken-framing.7z'
    build_7z(source,(a,b),corrupt_block=0)
    meta=inspect_7z(source)
    data=bytearray(source.read_bytes())
    # Find a C0 byte alteration that produces an invalid 0x03..0x7f
    # LZMA2 control, forcing fallback to bounded resynchronization.
    good = bytes(data)
    for value in range(1,256):
        data[:]=good
        data[meta.offset] = good[meta.offset] ^ value
        source.write_bytes(data)
        with DecryptedStream(source, meta, 'good', lambda: None) as stream:
            start=stream.read(1)[0]
        if 3 <= start <= 0x7f:
            break
    else:
        pytest.fail('could not construct invalid first control')
    files={}
    def publish(name,chunks,size,provenance):
        files[name]=b''.join(chunks)
        return True
    status=recover_aes_lzma2(source,'good',check=lambda:None,publish=publish)
    assert status['status']=='framing_resynchronized'
    assert status['resync_scan']['proven_files']==1
    assert files=={'recovered.bin':b}


def test_no_unchecked_files_survive_false_candidate_resets(tmp_path: Path):
    a,b=os.urandom(7000),os.urandom(8500)
    source=tmp_path/'bad-key.7z'
    build_7z(source,(a,b),corrupt_block=0)
    records=[]
    status=recover_aes_lzma2(source,'not-the-password',check=lambda:None,
        publish=lambda *args: records.append(args) or True)
    assert status['recovered']==0
    assert records==[]


def test_recovered_7z_names_cannot_traverse_outside_output(tmp_path: Path, monkeypatch):
    from app.archive_recovery import core
    source = tmp_path / 'escape.7z'
    out = tmp_path / 'results'
    out.mkdir()
    build_7z(source, (os.urandom(8000), os.urandom(7000)),
             corrupt_block=160, names=('bad.bin', '../outside.bin'))
    monkeypatch.setattr(core, '_libarchive', lambda *args: None)
    report = core.recover_archive(source, out, password='good', deep=True)
    assert not (tmp_path / 'outside.bin').exists()
    assert report['stats']['integrity_passed'] == 0
    assert any(x['reason']=='UNSAFE_PATH' for x in report['items'])


def test_deep_mode_upgrades_standard_entry_only_if_content_matches(tmp_path: Path, monkeypatch):
    from app.archive_recovery import core
    first, second = os.urandom(8500), os.urandom(9000)
    source = tmp_path / 'with-base.7z'
    out = tmp_path / 'results'
    out.mkdir()
    build_7z(source, (first, second), corrupt_block=160)
    def normal(source, root, fd, budget, results, password):
        core._record(root, fd, 'recovered.bin', iter((second,)), budget,
                     results, expected=len(second), provenance='libarchive')
    monkeypatch.setattr(core, '_libarchive', normal)
    report=core.recover_archive(source,out,password='good',deep=True)
    match=[r for r in report['items'] if r.get('name')=='recovered.bin']
    assert len(match)==1 and match[0]['status']=='integrity_passed'
    assert match[0]['provenance'].startswith('7z_aes_lzma2_')
    assert (out/'recovered.bin').read_bytes()==second


def test_deep_mode_never_upgrades_standard_entry_with_different_bytes(tmp_path: Path, monkeypatch):
    from app.archive_recovery import core
    first, second = os.urandom(8500), os.urandom(9000)
    source=tmp_path/'disagree.7z'
    out=tmp_path/'results'
    out.mkdir()
    build_7z(source,(first,second),corrupt_block=160)
    def normal(source, root, fd, budget, results, password):
        core._record(root, fd, 'recovered.bin', iter((b'Q'*len(second),)), budget,
                     results, expected=len(second), provenance='libarchive')
    monkeypatch.setattr(core, '_libarchive',normal)
    report=core.recover_archive(source,out,password='good',deep=True)
    entry=next(x for x in report['items'] if x.get('name')=='recovered.bin')
    assert entry['status']=='unverified'
    assert report['aes_lzma2_deep']['recovered']==0
    assert (out/'recovered.bin').read_bytes()==b'Q'*len(second)


def test_small_legacy_segment_limit_no_longer_drops_valid_files(tmp_path: Path, monkeypatch):
    from app.archive_recovery import aes_lzma2
    source = tmp_path/'limits.7z'
    build_7z(source,(os.urandom(3000),os.urandom(5000)))
    # This legacy limit still bounds damaged-framing CRC resynchronization,
    # but an intact stream must recover independently verified files.
    monkeypatch.setattr(aes_lzma2,'SEGMENT_LIMIT',1024)
    outputs=[]
    result=recover_aes_lzma2(source,'good',check=lambda:None,
                            publish=lambda *args: outputs.append(args) or True)
    assert result['recovered']==2
    assert len(outputs)==2


def test_realistic_aes_kdf_salt_iv_and_unicode_password(tmp_path: Path):
    # Typical 7z AES properties: SHA256 KDF 2**19 cycles, a 4-byte salt,
    # 16-byte IV, UTF-16LE password, AES-256-CBC.
    aes_props = b'\xd3\x3f' + b'salt' + bytes(range(16))
    a,b=os.urandom(1300),os.urandom(1900)
    source=tmp_path/'salted.7z'
    build_7z(source,(a,b),password='加密 test',aes_props=aes_props,corrupt_block=160)
    found={}
    result=recover_aes_lzma2(source,'加密 test',check=lambda:None,
        publish=lambda name,chunks,size,origin: found.setdefault(name,b''.join(chunks)) is not None)
    assert found=={'recovered.bin':b}
    assert result['recovered']==1