"""Files spanning intact dictionary resets must retain their verified prefix."""
import lzma
import zlib

import pytest

from app.archive_recovery.aes_lzma2 import Metadata, _recover_block


@pytest.mark.parametrize('damaged', [False, True])
def test_file_crossing_reset_requires_complete_crc_valid_bytes(tmp_path, damaged):
    """Keep contiguous prefixes across resets, but never publish damaged files."""
    first = b'A' * 4000
    second = b'B' * 4000
    tail = b'C' * 1000
    frames = [lzma.compress(data, format=lzma.FORMAT_RAW,
                           filters=[{'id': lzma.FILTER_LZMA2, 'dict_size': 1 << 20}])
              for data in (first, second + tail)]
    packed = bytearray(frames[0][:-1] + frames[1])
    if damaged:
        packed[10] ^= 0x40
    source = tmp_path / 'stream.bin'
    source.write_bytes(packed)
    meta = Metadata(0, len(packed), 9000, 1 << 20, None, [
        ('cross.bin', 0, 8000, zlib.crc32(first + second)),
        ('tail.bin', 8000, 1000, zlib.crc32(tail)),
    ])
    published = {}

    def publish(name, chunks, size, provenance):
        published[name] = b''.join(chunks)
        assert len(published[name]) == size
        return True

    _recover_block(source, meta, None, check=lambda: None, publish=publish,
                   attempted=set(), provenance_prefix='test', scratch_dir=tmp_path)
    expected = {'tail.bin': tail}
    if not damaged:
        expected['cross.bin'] = first + second
    assert published == expected
