"""Only synthetic scratch paths; validates isolated FUSE probe cleanup."""
import errno
import os

from app.batch.media_package_zfuse_probe import probe


def test_scratch_probe_positive_and_removes_its_entire_namespace(tmp_path):
    result = probe(tmp_path)
    assert result["compatible"], result
    assert result["cleanup_complete"]
    assert list(tmp_path.iterdir()) == []


def test_scratch_probe_reports_unsupported_hardlink_without_touching_neighbor(tmp_path, monkeypatch):
    sentinel = tmp_path / "real-user-file.txt"
    sentinel.write_bytes(b"do-not-touch")
    original = os.link

    def reject_link(source, dest, *args, **kwargs):
        raise OSError(errno.EOPNOTSUPP, "test-only zfuse hardlink rejection")

    monkeypatch.setattr(os, "link", reject_link)
    report = probe(tmp_path)
    monkeypatch.setattr(os, "link", original)
    assert report["compatible"] is False
    assert report["file_link"] is False
    assert report["cleanup_complete"] is True
    assert list(tmp_path.iterdir()) == [sentinel]
    assert sentinel.read_bytes() == b"do-not-touch"
