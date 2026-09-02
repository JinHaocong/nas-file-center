import json
from pathlib import Path


def test_build_group_command_has_safe_defaults_and_isolate(tmp_path):
    from app.scanners.fclones import build_group_command

    a = tmp_path / "A"; b = tmp_path / "B"
    a.mkdir(); b.mkdir()
    cmd = build_group_command(
        binary="fclones",
        roots=[a, b],
        allowed_roots=[tmp_path],
        isolate=True,
        min_size="100M",
        threads="hdd:4,1",
    )
    assert cmd[:2] == ["fclones", "group"]
    assert "--cache" in cmd
    assert cmd[cmd.index("--format") + 1] == "json"
    assert "--no-ignore" in cmd and "--hidden" in cmd and "--isolate" in cmd
    assert cmd[cmd.index("--min-size") + 1] == "100M"
    assert cmd[cmd.index("--threads") + 1] == "hdd:4,1"
    assert cmd[-2:] == [str(a.resolve()), str(b.resolve())]


def test_parse_fclones_report_supports_aliases():
    from app.scanners.parser import parse_fclones_report

    groups = parse_fclones_report(Path("tests/fixtures/fclones_report.json"))
    assert [(g.content_hash, g.file_size, len(g.files)) for g in groups] == [
        ("abc123", 4, 2),
        ("def456", 7, 3),
    ]
    assert groups[1].files[0] == Path("/data/A/二.txt")


def test_run_scan_writes_report_atomically(tmp_path):
    from app.scanners.fclones import run_scan

    fake = tmp_path / "fake-fclones"
    fake.write_text(
        "#!/bin/sh\nprintf '%s' '{\"groups\":[{\"size\":1,\"hash\":\"h\",\"files\":[\"/data/a\",\"/data/b\"]}]}'\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    report = tmp_path / "reports" / "job.json"
    completed = run_scan([str(fake), "group"], report_path=report, home_dir=tmp_path / "home")
    assert completed.returncode == 0
    assert json.loads(report.read_text())["groups"][0]["hash"] == "h"
    assert not report.with_suffix(report.suffix + ".partial").exists()
