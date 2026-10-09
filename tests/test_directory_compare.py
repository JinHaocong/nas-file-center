from pathlib import Path

import pytest

from app.batch import directory_compare
from app.batch.directory_compare import compare_directories, verify_directory_pair


def diff(a: Path, b: Path, *, quarantine=None):
    return compare_directories(
        str(a), str(b),
        allowed_roots=[a.parent], quarantine_root=quarantine,
    )


def verify(a: Path, b: Path, relative: str):
    return verify_directory_pair(
        str(a), str(b), relative,
        allowed_roots=[a.parent], quarantine_root=a.parent / ".trash",
    )


def roots(tmp_path):
    a = tmp_path / "A"
    b = tmp_path / "B"
    a.mkdir()
    b.mkdir()
    return a, b


def by_path(result):
    return {row["relative_path"]: row for row in result["items"]}


def test_read_only_relative_path_categories_recursive(tmp_path):
    a, b = roots(tmp_path)
    (a / "nested").mkdir()
    (b / "nested").mkdir()
    (a / "nested" / "same-size.txt").write_text("ABCD")
    (b / "nested" / "same-size.txt").write_text("WXYZ")
    (a / "nested" / "size.txt").write_text("X")
    (b / "nested" / "size.txt").write_text("long")
    (a / "only-a.txt").write_text("a")
    (b / "only-b.txt").write_text("b")
    (a / "different-type").mkdir()
    (b / "different-type").write_text("file")

    result = by_path(diff(a, b))
    assert result["nested"]["status"] == "both_directories"
    assert result["nested/same-size.txt"]["status"] == "same_size_unverified"
    assert result["nested/size.txt"]["status"] == "size_different"
    assert result["only-a.txt"]["status"] == "only_a"
    assert result["only-b.txt"]["status"] == "only_b"
    assert result["different-type"]["status"] == "type_mismatch"
    assert (a / "only-a.txt").read_text() == "a"
    assert (b / "only-b.txt").read_text() == "b"


def test_sha256_distinguishes_equal_size_but_different_content(tmp_path):
    a, b = roots(tmp_path)
    (a / "x").write_bytes(b"ABCD")
    (b / "x").write_bytes(b"WXYZ")
    assert by_path(diff(a, b))["x"]["status"] == "same_size_unverified"
    res = verify(a, b, "x")
    assert res["same_content"] is False
    (b / "x").write_bytes(b"ABCD")
    assert verify(a, b, "x")["same_content"] is True


def test_symlink_leaf_and_nested_symlink_are_not_traversed(tmp_path):
    a, b = roots(tmp_path)
    external = tmp_path / "outside"
    external.mkdir()
    (external / "secret").write_text("sensitive")
    (a / "link-directory").symlink_to(external, target_is_directory=True)
    (a / "link-file").symlink_to(external / "secret")
    (a / "normal").write_text("safe")
    result = diff(a, b)
    assert by_path(result) == {
        "normal": {
            "relative_path": "normal", "kind_a": "file", "kind_b": None,
            "size_a": 4, "size_b": None, "status": "only_a",
        },
    }
    assert result["skipped_symlinks_a"] == 2
    with pytest.raises(OSError):
        verify(a, b, "link-file")
    assert (external / "secret").read_text() == "sensitive"


def test_reserved_quarantine_skipped_from_both_trees(tmp_path):
    a, b = roots(tmp_path)
    trash = a / ".trash"
    trash.mkdir()
    (trash / "hidden.txt").write_text("hidden")
    (a / "visible.txt").write_text("visible")
    result = diff(a, b, quarantine=trash)
    assert set(by_path(result)) == {"visible.txt"}
    with pytest.raises(ValueError, match="Quarantine"):
        verify_directory_pair(
            str(a), str(b), ".trash/hidden.txt",
            allowed_roots=[tmp_path], quarantine_root=trash,
        )


def test_reject_same_overlap_outside_and_missing(tmp_path):
    a, b = roots(tmp_path)
    (a / "child").mkdir()
    with pytest.raises(ValueError, match="non-overlapping"):
        diff(a, a)
    with pytest.raises(ValueError, match="non-overlapping"):
        compare_directories(str(a), str(a / "child"), allowed_roots=[tmp_path])
    with pytest.raises(ValueError, match="outside configured roots"):
        compare_directories(str(a), str(tmp_path.parent), allowed_roots=[tmp_path])
    with pytest.raises(ValueError, match="does not exist"):
        compare_directories(str(a), str(tmp_path / "missing"), allowed_roots=[tmp_path])
    with pytest.raises(ValueError, match="absolute"):
        compare_directories("relative", str(b), allowed_roots=[tmp_path])


def test_bounded_directory_scan_fails_without_partial_results(tmp_path, monkeypatch):
    a, b = roots(tmp_path)
    for name in ("one", "two", "three"):
        (a / name).write_text(name)
    monkeypatch.setattr(directory_compare, "MAX_ENTRIES_PER_ROOT", 2)
    with pytest.raises(ValueError, match="narrow the comparison roots"):
        diff(a, b)


def test_hash_rejects_unsafe_paths_nonfiles_and_oversize(tmp_path, monkeypatch):
    a, b = roots(tmp_path)
    (a / "folder").mkdir()
    (b / "folder").mkdir()
    (a / "tiny").write_text("hello")
    (b / "tiny").write_text("hello")
    for relative in ("../other", "/etc/passwd", "folder/../tiny", "folder"):
        with pytest.raises((ValueError, OSError)):
            verify(a, b, relative)
    monkeypatch.setattr(directory_compare, "MAX_VERIFY_FILE_BYTES", 2)
    with pytest.raises(ValueError, match="limit"):
        verify(a, b, "tiny")


def test_api_requires_authentication_and_does_not_change_files(tmp_path):
    from fastapi.testclient import TestClient
    from app.config import Settings
    from app.main import create_app

    data = tmp_path / "data"
    config = tmp_path / "config"
    data.mkdir()
    config.mkdir()
    a = data / "A"
    b = data / "B"
    a.mkdir()
    b.mkdir()
    (a / "same.txt").write_bytes(b"hello")
    (b / "same.txt").write_bytes(b"hello")
    settings = Settings(
        _env_file=None,
        CONFIG_DIR=str(config),
        DATA_MOUNT=str(data),
        ALLOWED_ROOTS=str(data),
        QUARANTINE_ROOT=str(data / ".trash"),
        ALLOW_MUTATION=False, ALLOW_DELETE=False,
        INITIAL_ADMIN_USERNAME="admin",
        INITIAL_ADMIN_PASSWORD="test-password-123",
    )
    with TestClient(create_app(settings)) as client:
        url = "/api/directories/compare/preview"
        payload = {"root_a": str(a), "root_b": str(b)}
        assert client.post(url, json=payload).status_code == 401
        client.headers.update({"Origin": "http://testserver"})
        login = client.post("/api/auth/login", json={
            "username": "admin", "password": "test-password-123",
        })
        assert login.status_code == 200
        preview = client.post(url, json=payload)
        assert preview.status_code == 200, preview.text
        assert preview.json()["counts"]["same_size_unverified"] == 1
        match = client.post("/api/directories/compare/verify", json={
            **payload, "relative_path": "same.txt",
        })
        assert match.status_code == 200, match.text
        assert match.json()["same_content"] is True
        assert (a / "same.txt").read_bytes() == (b / "same.txt").read_bytes() == b"hello"
        blocked = client.post(url, json={
            "root_a": str(a), "root_b": str(tmp_path),
        })
        assert blocked.status_code == 400
        malformed = client.post(url, json={**payload, "unknown": "bad"})
        assert malformed.status_code == 422
