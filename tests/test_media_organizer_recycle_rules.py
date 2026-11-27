import pytest

from app.batch.media_organizer_recycle_rules import check


@pytest.mark.parametrize(("name", "payload", "reason"), [
    ("原地址.URL", b"[InternetShortcut]\nURL=https://example.test", "url_shortcut"),
    ("链接.TXT", b"\xef\xbb\xbfhttps://example.test/a\nhttps://example.test/b\n", "links_only"),
    ("链接合集.txt", b"https://example.test/a http://example.test/b", "links_only"),
    ("广告.txt", "【推广】\n请关注公众号：演示账号\nhttps://example.test/a".encode("gb18030"), "promotion"),
    ("下载说明.txt", "更多资源请访问：https://example.test/example".encode("utf-16"), "promotion"),
    ("推广.txt", "拍摄日期 2026 年 11 月\n作品说明和来源\nhttps://example.test/a".encode(), None),
    ("作品说明.txt", "【推广】\n备注：作品分上下集\nhttps://example.test/a".encode(), None),
    ("作品说明.txt", "作者公众号：示例账号\n原作品链接：https://example.test/a".encode(), None),
    ("链接.txt", b"https://?invalid\n", None),
    ("字幕.srt", b"https://example.test/a", None),
    ("空.txt", b"\n\t", None),
    ("伪装文本.txt", b"https://example.test/a\x00\x01binary", None),
    ("超长.txt", b"https://example.test/a\n" + b" " * 65536, None),
])
def test_recycle_candidates_only_include_shortcuts_and_standalone_promotion(tmp_path, name, payload, reason):
    path = tmp_path / name
    path.write_bytes(payload)

    assert check(path, path.lstat()) == reason


def test_replaced_file_and_symlink_are_never_recycle_candidates(tmp_path):
    path = tmp_path / "原地址.txt"
    path.write_text("https://example.test/old")
    expected = path.lstat()
    replacement = tmp_path / "替换.txt"
    replacement.write_text("https://example.test/new")
    replacement.replace(path)

    assert check(path, expected) is None

    symlink = tmp_path / "地址.url"
    symlink.symlink_to(path)
    assert check(symlink, symlink.lstat()) is None
    folder = tmp_path / "标为链接.url"
    folder.mkdir()
    assert check(folder, folder.lstat()) is None


def test_recycle_classifier_does_not_follow_parent_symlink(tmp_path):
    folder = (tmp_path / "原目录").resolve()
    folder.mkdir()
    path = folder / "地址.txt"
    path.write_text("https://example.test/a")
    alias = folder.with_name("目录链接")
    alias.symlink_to(folder, target_is_directory=True)

    assert check(alias / path.name, path.lstat()) is None
