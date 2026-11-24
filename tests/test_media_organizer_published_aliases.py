"""Lift verified P/V buckets out of a sole dated work alias."""

import errno
import os
from pathlib import Path
import stat

import pytest

from app.batch.media_organizer_planner import iter_organizing_previews
from tests.test_media_organizer_batch import _batch, _preview, _run_next
from tests.test_media_organizer_split_work import put_files
from tests.test_media_package_execute_jobs import _fixture


_BUCKETS = {"P [2 8B]/001.JPG": b"pic1", "P [2 8B]/002.jpg": b"pic2",
            "V [1 4B]/001.MOV": b"clip"}


@pytest.mark.parametrize(("title", "alias"), [
    ("18.03.01-会员版  2P1V", "昵称18.03.01"),
    ("18.10.07 海边小屋(2P+1V)", "[样例]海边小屋"),
    ("18.10.19 海边小屋2P1V(售价266元)★", "昵称-海边小屋"),
    ("18.12.05 白衬衫  2P1V12M", "EX18.12.05"),
    ("19.01.23 更新作品【2P1V", "昵称19.01.23"),
])
def test_published_alias_buckets_move_to_the_work_root_within_its_volume(tmp_path, title, alias):
    client, settings, _ = _fixture(tmp_path)
    scope = settings.data_mount / "Else/2610/261001/作者(昵称)/网盘"
    first_volume = scope / "WJJ-01"
    second_volume = scope / "WJJ-02"
    work = first_volume / "2018.03【来源】" / title
    put_files(work / alias, _BUCKETS)
    peer = second_volume / "2018.04【来源】" / "独立作品"
    put_files(peer, {"001.jpg": b"peer"})

    preview = _preview(client, settings, scope)
    assert {(row["unit"], row["status"]) for row in preview["units"]} == {
        (str(work), "ready"), (str(peer), "already_organized"),
    }
    unit = next(row for row in preview["units"] if row["unit"] == str(work))
    assert [(Path(move["source"]).relative_to(work / alias), Path(move["target"]).relative_to(work))
            for move in unit["sample_moves"]] == [(Path(name), Path(name)) for name in _BUCKETS]
    assert unit["renamed_count"] == 0

    batch = _batch(client, preview)
    assert _run_next(settings, batch)
    result = client.get(f"/api/media-organizer/batches/{batch}").json()
    assert result["summary"]["success_count"] == 1, result
    assert {path.relative_to(work).as_posix(): path.read_bytes()
            for path in work.rglob("*") if path.is_file()} == _BUCKETS
    assert not (work / alias).exists()
    assert (peer / "001.jpg").read_bytes() == b"peer"
    assert set(scope.iterdir()) == {first_volume, second_volume}
    again = _preview(client, settings, scope)
    assert again["summary"]["ready_count"] == again["summary"]["blocked_count"] == 0, again


@pytest.mark.parametrize(("title", "alias", "override"), [
    ("18.12.31 新年合集(2P+1V)★", "昵称 12.31", {}),
    ("18.12.31 海边小屋(2P+1V)", "海边小屋 压缩版", {}),
    ("18.12.31 海边小屋(2P+1V)", "陌生前缀-海边小屋", {}),
    ("18.12.31 海边小屋(2P+2V)", "海边小屋", {}),
    ("18.12.31 海边小屋(2P+1V)", "海边小屋", {"P [2 8B]/003.jpg": b"pic3"}),
    ("18.12.31 海边小屋(2P+1V)", "海边小屋", {"V [1 4B]/002.MOV": b"clip"}),
    ("18.12.31 海边小屋【2P1V", "海边小屋", {}),
])
def test_published_alias_requires_identity_and_canonical_bucket_inventory(tmp_path, title, alias, override):
    work = tmp_path / "2610/261001/作者(昵称)/网盘" / title
    if "V [1 4B]/002.MOV" in override:
        replacement = {key: value for key, value in _BUCKETS.items() if key != "V [1 4B]/001.MOV"}
    else:
        replacement = _BUCKETS
    put_files(work / alias, replacement | override)
    rows = list(iter_organizing_previews(work, allowed_roots=[tmp_path]))
    assert all(row["unit"] != str(work) for row in rows)


def test_late_outer_sibling_invalidates_the_published_alias_preview(tmp_path):
    client, settings, _ = _fixture(tmp_path)
    work = settings.data_mount / "Else/18.10.07 海边小屋(2P+1V)"
    alias = work / "海边小屋"
    put_files(alias, _BUCKETS)
    preview = _preview(client, settings, work)
    assert preview["summary"]["ready_count"] == 1
    put_files(work, {"独立作品/001.jpg": b"peer"})

    batch = _batch(client, preview)
    assert _run_next(settings, batch)
    result = client.get(f"/api/media-organizer/batches/{batch}").json()
    assert result["summary"]["conflict_count"] == 1, result
    assert {path.relative_to(alias).as_posix(): path.read_bytes()
            for path in alias.rglob("*") if path.is_file()} == _BUCKETS


def test_published_alias_runs_with_file_based_group_publication(tmp_path, monkeypatch):
    from app.batch import media_package_execution

    client, settings, _ = _fixture(tmp_path, fuse_compat=True)
    work = settings.data_mount / "Else/18.10.07 海边小屋(2P+1V)"
    put_files(work / "海边小屋", _BUCKETS)
    preview = _preview(client, settings, work)
    rename_at = media_package_execution.rename_noreplace_at

    def refuse_directory_rename(source_fd, source, target_fd, target):
        if stat.S_ISDIR(os.stat(source, dir_fd=source_fd, follow_symlinks=False).st_mode):
            raise OSError(errno.EOPNOTSUPP, "Directory rename is unavailable")
        return rename_at(source_fd, source, target_fd, target)

    def refuse_plain_rename(source, target):
        raise OSError(errno.EOPNOTSUPP, "Directory no-replace is unverified")

    monkeypatch.setattr(media_package_execution, "rename_noreplace_at", refuse_directory_rename)
    monkeypatch.setattr(media_package_execution, "rename_directory_noreplace_compat", refuse_plain_rename)
    batch = _batch(client, preview)
    assert _run_next(settings, batch)
    result = client.get(f"/api/media-organizer/batches/{batch}").json()
    assert result["summary"]["success_count"] == 1, result
    assert {path.relative_to(work).as_posix(): path.read_bytes()
            for path in work.rglob("*") if path.is_file()} == _BUCKETS
    assert _preview(client, settings, work)["summary"]["already_organized_count"] == 1
