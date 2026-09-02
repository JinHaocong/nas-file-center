from fastapi.testclient import TestClient


def make_client(tmp_path, *, allow_mutation=False):
    data = tmp_path / "data"; data.mkdir()
    config = tmp_path / "config"; config.mkdir()
    from app.config import Settings
    from app.main import create_app
    settings = Settings(
        _env_file=None,
        CONFIG_DIR=str(config),
        DATA_MOUNT=str(data),
        ALLOWED_ROOTS=str(data),
        QUARANTINE_ROOT=str(data / ".trash"),
        ALLOW_MUTATION=allow_mutation,
        ALLOW_DELETE=False,
    )
    return TestClient(create_app(settings)), data


def test_dashboard_and_navigation_are_chinese_and_self_contained(tmp_path):
    client, _ = make_client(tmp_path)
    response = client.get("/")
    assert response.status_code == 200
    assert "NAS 文件中心" in response.text
    assert "扫描去重" in response.text
    assert "只读安全模式" in response.text
    assert "/static/app.css" in response.text
    assert "cdn" not in response.text.lower()
    assert client.get("/static/app.css").status_code == 200
    assert client.get("/static/app.js").status_code == 200


def test_scan_form_creates_job_and_scan_detail_page(tmp_path):
    client, data = make_client(tmp_path)
    a = data / "A"; b = data / "B"; a.mkdir(); b.mkdir()
    response = client.post("/ui/scans", data={
        "name": "测试 A/B",
        "roots_text": f"{a}\n{b}",
        "isolate": "on",
        "min_size": "",
        "name_patterns_text": "",
        "exclude_patterns_text": "",
    }, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/ui/scans/1"

    detail = client.get("/ui/scans/1")
    assert detail.status_code == 200
    assert "测试 A/B" in detail.text
    assert "排队中" in detail.text
    assert str(a) in detail.text


def test_rename_and_organizer_preview_pages_do_not_mutate(tmp_path):
    client, data = make_client(tmp_path)
    file = data / "same.jpg"; file.write_text("x")
    rename = client.post("/ui/rename", data={
        "paths_text": str(file),
        "regex_pattern": "",
        "regex_replacement": "",
        "prefix": "NEW-",
        "suffix": "",
        "number_start": "",
        "number_width": "3",
        "include_parent": "",
    })
    assert rename.status_code == 200
    assert "NEW-same.jpg" in rename.text
    assert file.exists()

    root = data / "少女映画"; root.mkdir()
    folder = root / "001 少女映画 A [9P 1GB]"; folder.mkdir()
    (folder / "a.jpg").write_bytes(b"x")
    organizer = client.post("/ui/organizer", data={"root": str(root)})
    assert organizer.status_code == 200
    assert "001 少女映画 A [1P 0.0MB]" in organizer.text
    assert folder.exists()


def test_plan_page_disables_execute_in_safe_mode_and_aux_pages_render(tmp_path):
    client, data = make_client(tmp_path, allow_mutation=False)
    source = data / "x.txt"; source.write_text("x")
    created = client.post("/api/plans", json={
        "name": "touch",
        "kind": "touch",
        "items": [{"operation": "touch", "source": str(source)}],
    })
    plan_id = created.json()["id"]
    page = client.get(f"/ui/plans/{plan_id}")
    assert page.status_code == 200
    assert "只读安全模式" in page.text
    assert 'data-action="execute" disabled' in page.text

    for path, text in [
        ("/ui/jobs", "任务中心"),
        ("/ui/audit", "审计日志"),
        ("/ui/settings", "运行设置"),
        ("/ui/indexes", "文件索引"),
        ("/ui/plans", "执行计划"),
    ]:
        response = client.get(path)
        assert response.status_code == 200
        assert text in response.text
