from __future__ import annotations

import os
from pathlib import Path
from fastapi.testclient import TestClient

from app.auth.password import hash_password
from app.config import Settings
from app.db import create_engine_and_session, init_db
from app.main import create_app
from app.models import User


def _create_test_app(tmp_path: Path, allow_mutation: bool = True, allowed_roots_raw: str | None = None):
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    db_path = config_dir / "app.db"
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    if allowed_roots_raw is None:
        allowed_roots_raw = str(data_dir)

    settings = Settings(
        app_name="TestApp",
        secret_key="test-secret-key-at-least-32-bytes-long",
        database_path=db_path,
        config_dir=config_dir,
        reports_dir=config_dir / "reports",
        backups_dir=config_dir / "backups",
        logs_dir=config_dir / "logs",
        fclones_home=config_dir / "fclones",
        quarantine_root=data_dir / ".quarantine",
        allowed_roots_raw=allowed_roots_raw,
        allow_mutation=allow_mutation,
    )
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine, db_path=db_path)

    with SessionLocal() as session:
        user = User(
            username="admin",
            password_hash=hash_password("admin_password_123"),
            role="admin",
            is_active=True,
        )
        session.add(user)
        session.commit()

    app = create_app(settings)
    return app, data_dir, settings


def _get_auth_client(app: any) -> TestClient:
    client = TestClient(app)
    client.headers.update({"Origin": "http://testserver"})
    resp = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "admin_password_123"},
    )
    assert resp.status_code == 200
    return client


def test_list_filesystem_success(tmp_path: Path):
    app, data_dir, _ = _create_test_app(tmp_path)
    # Create subdirectories and files
    (data_dir / "Download").mkdir()
    (data_dir / "Photos").mkdir()
    (data_dir / "少女映画").mkdir()
    (data_dir / "Special #1 [2026]").mkdir()
    (data_dir / "test.txt").write_text("hello")

    client = _get_auth_client(app)

    # 1. List /data directory (directories only by default)
    resp = client.get(f"/api/filesystem/list?path={data_dir}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["path"] == str(data_dir.resolve())
    assert data["parent"] is None  # /data is root, parent is None

    names = [item["name"] for item in data["items"]]
    assert "Download" in names
    assert "Photos" in names
    assert "少女映画" in names
    assert "Special #1 [2026]" in names
    assert "test.txt" not in names  # directories_only=True by default

    # 2. List /data with directories_only=false
    resp_all = client.get(f"/api/filesystem/list?path={data_dir}&directories_only=false")
    assert resp_all.status_code == 200
    all_names = [item["name"] for item in resp_all.json()["items"]]
    assert "test.txt" in all_names

    # 3. List Chinese subdirectory
    resp_cn = client.get(f"/api/filesystem/list?path={data_dir / '少女映画'}")
    assert resp_cn.status_code == 200
    assert resp_cn.json()["path"] == str((data_dir / "少女映画").resolve())
    assert resp_cn.json()["parent"] == str(data_dir.resolve())


def test_list_filesystem_default_root_and_custom_subroot(tmp_path: Path):
    # 1. When path is omitted, backend defaults to allowed_roots[0]
    app1, data_dir, _ = _create_test_app(tmp_path)
    (data_dir / "FolderA").mkdir()
    client1 = _get_auth_client(app1)

    resp1 = client1.get("/api/filesystem/list")
    assert resp1.status_code == 200
    res1 = resp1.json()
    assert res1["path"] == str(data_dir.resolve())
    assert "FolderA" in [item["name"] for item in res1["items"]]

    # 2. When ALLOWED_ROOTS is a subroot /data/subroot, omitting path defaults to /data/subroot, NOT /data
    subroot = data_dir / "subroot"
    subroot.mkdir()
    (subroot / "NestedFolder").mkdir()
    app2, _, _ = _create_test_app(tmp_path / "subroot_test", allowed_roots_raw=str(subroot))
    client2 = _get_auth_client(app2)

    resp2 = client2.get("/api/filesystem/list")
    assert resp2.status_code == 200
    res2 = resp2.json()
    assert res2["path"] == str(subroot.resolve())
    assert "NestedFolder" in [item["name"] for item in res2["items"]]
    # Accessing outside /data is refused
    resp_outside = client2.get(f"/api/filesystem/list?path={data_dir}")
    assert resp_outside.status_code in {400, 422}


def test_list_filesystem_server_side_pagination_and_over_1000_items(tmp_path: Path):
    app, data_dir, _ = _create_test_app(tmp_path)
    large_dir = data_dir / "LargeFolder"
    large_dir.mkdir()

    # Create 1050 subdirectories
    for i in range(1050):
        (large_dir / f"dir_{i:04d}").mkdir()

    client = _get_auth_client(app)

    # Page 1 (100 items)
    resp_p1 = client.get(f"/api/filesystem/list?path={large_dir}&page=1&page_size=100")
    assert resp_p1.status_code == 200
    data_p1 = resp_p1.json()
    assert data_p1["total"] == 1050
    assert data_p1["page"] == 1
    assert data_p1["page_size"] == 100
    assert data_p1["has_more"] is True
    assert len(data_p1["items"]) == 100
    assert data_p1["items"][0]["name"] == "dir_0000"
    assert data_p1["items"][99]["name"] == "dir_0099"

    # Middle Page 5 (100 items)
    resp_p5 = client.get(f"/api/filesystem/list?path={large_dir}&page=5&page_size=100")
    assert resp_p5.status_code == 200
    data_p5 = resp_p5.json()
    assert data_p5["total"] == 1050
    assert data_p5["page"] == 5
    assert data_p5["has_more"] is True
    assert len(data_p5["items"]) == 100
    assert data_p5["items"][0]["name"] == "dir_0400"

    # Last Page 11 (Remaining 50 items)
    resp_p11 = client.get(f"/api/filesystem/list?path={large_dir}&page=11&page_size=100")
    assert resp_p11.status_code == 200
    data_p11 = resp_p11.json()
    assert data_p11["total"] == 1050
    assert data_p11["page"] == 11
    assert data_p11["has_more"] is False
    assert len(data_p11["items"]) == 50
    assert data_p11["items"][-1]["name"] == "dir_1049"


def test_list_filesystem_search_filter(tmp_path: Path):
    app, data_dir, _ = _create_test_app(tmp_path)
    (data_dir / "Movie_2025").mkdir()
    (data_dir / "Movie_2026").mkdir()
    (data_dir / "Documentary").mkdir()

    client = _get_auth_client(app)
    resp = client.get(f"/api/filesystem/list?path={data_dir}&search=2026")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert len(data["items"]) == 1
    assert data["items"][0]["name"] == "Movie_2026"


def test_list_filesystem_security_traversal_and_escapes(tmp_path: Path):
    app, data_dir, _ = _create_test_app(tmp_path)
    client = _get_auth_client(app)

    # 1. Traversal outside ALLOWED_ROOTS
    resp = client.get(f"/api/filesystem/list?path={data_dir}/../..")
    assert resp.status_code in {400, 422}

    # 2. Explicit /etc or /root outside allowed roots
    resp_etc = client.get("/api/filesystem/list?path=/etc")
    assert resp_etc.status_code in {400, 422}

    # 3. Symlink escape test: Symlink inside /data pointing to /tmp (outside /data)
    outside_dir = tmp_path / "outside_secret"
    outside_dir.mkdir()
    escape_link = data_dir / "escape_link"
    try:
        escape_link.symlink_to(outside_dir)
    except OSError:
        pass

    if escape_link.is_symlink():
        resp = client.get(f"/api/filesystem/list?path={data_dir}")
        assert resp.status_code == 200
        # Symlink pointing outside allowed roots must NOT be listed or accessible
        names = [item["name"] for item in resp.json()["items"]]
        assert "escape_link" not in names


def test_list_filesystem_nonexistent_and_file_as_dir(tmp_path: Path):
    app, data_dir, _ = _create_test_app(tmp_path)
    client = _get_auth_client(app)

    # 1. Non-existent path inside allowed root -> 404
    resp_404 = client.get(f"/api/filesystem/list?path={data_dir / 'NonExistentDir'}")
    assert resp_404.status_code == 404

    # 2. File path requested as directory -> 400
    file_path = data_dir / "file.txt"
    file_path.write_text("content")
    resp_file = client.get(f"/api/filesystem/list?path={file_path}")
    assert resp_file.status_code == 400


def test_list_filesystem_unauthenticated_and_readonly_safe(tmp_path: Path):
    # 1. Unauthenticated request -> 401
    app, data_dir, _ = _create_test_app(tmp_path, allow_mutation=False)
    unauth_client = TestClient(app)
    resp_unauth = unauth_client.get(f"/api/filesystem/list?path={data_dir}")
    assert resp_unauth.status_code == 401

    # 2. Authenticated read-only mode (allow_mutation=false) allows browsing
    auth_client = _get_auth_client(app)
    resp_readonly = auth_client.get(f"/api/filesystem/list?path={data_dir}")
    assert resp_readonly.status_code == 200


def test_frontend_directory_picker_source_contract_no_hardcoded_data():
    comp_dir = (
        Path(__file__).resolve().parent.parent
        / "frontend"
        / "src"
        / "components"
        / "DirectoryPicker"
    )
    picker_tsx = (comp_dir / "DirectoryPicker.tsx").read_text(encoding="utf-8")
    modal_tsx = (comp_dir / "DirectoryPickerModal.tsx").read_text(encoding="utf-8")
    breadcrumb_tsx = (comp_dir / "PathBreadcrumb.tsx").read_text(encoding="utf-8")

    assert "initialPath={singleValue || '/data'}" not in picker_tsx
    assert "useState<string>('/data')" not in modal_tsx
    assert "allowedRoots = ['/data']" not in breadcrumb_tsx


def test_scans_page_source_contract_no_default_data():
    scans_file = (
        Path(__file__).resolve().parent.parent
        / "frontend"
        / "src"
        / "pages"
        / "Scans"
        / "index.tsx"
    )
    content = scans_file.read_text(encoding="utf-8")
    assert "initialValue={['/data']}" not in content


def test_filesystem_list_source_no_iterdir():
    service_file = (
        Path(__file__).resolve().parent.parent
        / "app"
        / "service.py"
    )
    content = service_file.read_text(encoding="utf-8")
    assert "safe_path.iterdir()" not in content
    assert "os.scandir" in content


def test_path_breadcrumb_allowed_roots_relative_navigation_contract():
    breadcrumb_file = (
        Path(__file__).resolve().parent.parent
        / "frontend"
        / "src"
        / "components"
        / "DirectoryPicker"
        / "PathBreadcrumb.tsx"
    )
    content = breadcrumb_file.read_text(encoding="utf-8")
    # Verify relative derivation logic based on matched allowedRoot
    assert "matchingRoots" in content
    assert "cleanBaseRoot" in content
    assert "cleanCurrent.slice(cleanBaseRoot.length)" in content


def test_filesystem_natural_sort_ordering(tmp_path: Path):
    app, data_dir, _ = _create_test_app(tmp_path)
    client = _get_auth_client(app)

    # Intentionally create in non-sorted order
    (data_dir / "folder10").mkdir()
    (data_dir / "folder2").mkdir()
    (data_dir / "folder1").mkdir()
    (data_dir / "folder11").mkdir()
    (data_dir / "folder3").mkdir()

    # Create files to test directory-first and file natural sorting
    (data_dir / "file10.txt").write_text("10")
    (data_dir / "file2.txt").write_text("2")
    (data_dir / "file1.txt").write_text("1")

    # 1. Directories only (default)
    resp = client.get(f"/api/filesystem/list?path={data_dir}")
    assert resp.status_code == 200
    dir_names = [item["name"] for item in resp.json()["items"]]
    assert dir_names == ["folder1", "folder2", "folder3", "folder10", "folder11"]

    # 2. All items: directories first, then files, both in natural sort order
    resp_all = client.get(f"/api/filesystem/list?path={data_dir}&directories_only=false")
    assert resp_all.status_code == 200
    all_names = [item["name"] for item in resp_all.json()["items"]]
    assert all_names == [
        "folder1",
        "folder2",
        "folder3",
        "folder10",
        "folder11",
        "file1.txt",
        "file2.txt",
        "file10.txt",
    ]


def test_filesystem_bounded_heap_and_no_full_list_in_source():
    service_file = (
        Path(__file__).resolve().parent.parent
        / "app"
        / "service.py"
    )
    content = service_file.read_text(encoding="utf-8")
    assert "safe_path.iterdir()" not in content
    assert "candidate_entries" not in content
    assert "heapq.heappush" in content
    assert "heapq.heapreplace" in content
    assert "natural_sort_key" in content


def test_directory_picker_checkbox_stop_propagation_source_contract():
    modal_file = (
        Path(__file__).resolve().parent.parent
        / "frontend"
        / "src"
        / "components"
        / "DirectoryPicker"
        / "DirectoryPickerModal.tsx"
    )
    content = modal_file.read_text(encoding="utf-8")
    # Checkbox wrappers must have stopPropagation
    assert "onClick={(e) => e.stopPropagation()}" in content
    # Popconfirm delete wrapper must have stopPropagation
    assert "onConfirm={() => delFavMutation.mutate(fav.id)}" in content
