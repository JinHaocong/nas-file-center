import pytest

from app.batch.media_organizer_recycle_rules import check, matches_reviewed_candidate


@pytest.mark.parametrize(("name", "payload", "reason"), [
    ("原地址.URL", b"[InternetShortcut]\nURL=https://example.test", "url_shortcut"),
    ("链接.TXT", b"\xef\xbb\xbfhttps://example.test/a\nhttps://example.test/b\n", "text_file"),
    ("广告.txt", "【推广】\n请关注公众号：演示账号\nhttps://example.test/a".encode("gb18030"), "text_file"),
    ("作品说明.txt", "拍摄日期 2026 年 11 月\n作品说明和来源".encode(), "text_file"),
    ("提取码.TxT", b"passcode: demo", "text_file"),
    ("字幕.srt", b"https://example.test/a", None),
    ("说明.txt.bak", b"draft", None),
    ("空.txt", b"", "text_file"),
    ("伪装文本.txt", b"\x00\x01binary", "text_file"),
    pytest.param("超长.txt", b" " * 65537, "text_file", id="large-txt"),
    (".txt", b"notes", "text_file"),
    (".url", b"", "url_shortcut"),
])
def test_recycle_candidates_use_case_insensitive_file_name_suffix(tmp_path, name, payload, reason):
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


@pytest.mark.parametrize('previous_reason', ['links_only', 'promotion'])
def test_existing_reviewed_text_labels_still_match_unchanged_files(tmp_path, previous_reason):
    text = tmp_path / '说明.txt'
    shortcut = tmp_path / '地址.url'
    text.write_text('https://example.test/a')
    shortcut.write_bytes(b'')

    assert matches_reviewed_candidate(text, text.lstat(), previous_reason)
    assert not matches_reviewed_candidate(shortcut, shortcut.lstat(), previous_reason)
