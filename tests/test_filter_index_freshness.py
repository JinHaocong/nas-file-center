from __future__ import annotations

from pathlib import Path
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.service import FileCenterService


def test_filter_preview_index_freshness_lifecycle(tmp_path: Path):
    """Rule 30: Index freshness lifecycle verification:
    1. Create a.txt on disk
    2. Reindex root -> Preview shows a.txt (preview_source='index', live_filesystem_verified=False)
    3. Delete a.txt on disk (do NOT reindex) -> Preview STILL shows a.txt
    4. Reindex root -> Preview no longer shows a.txt
    """
    data = tmp_path / "data"
    data.mkdir(parents=True, exist_ok=True)
    config = tmp_path / "config"
    config.mkdir(parents=True, exist_ok=True)

    folder = data / "freshness_test"
    folder.mkdir()

    file_a = folder / "a.txt"
    file_a.write_text("hello world")

    settings = Settings(
        config_dir=config,
        data_mount=data,
        allowed_roots_raw=str(data),
        quarantine_root=data / ".trash",
        initial_admin_username="admin",
        initial_admin_password="AdminPassword123!",
    )
    service = FileCenterService(settings)
    app = create_app(settings)
    client = TestClient(app)

    # Login
    login_resp = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "AdminPassword123!"},
        headers={"Origin": "http://testserver"},
    )
    assert login_resp.status_code == 200

    # Step 1 & 2: Reindex root with a.txt on disk
    index_res = service.reindex_root(str(folder))
    assert index_res["files"] == 1

    payload = {
        "roots": [str(folder)],
        "filter": {
            "field": "name",
            "operator": "eq",
            "value": "a.txt",
        },
    }

    resp1 = client.post(
        "/api/filters/preview",
        json=payload,
        headers={"Origin": "http://testserver"},
    )
    assert resp1.status_code == 200, resp1.text
    data1 = resp1.json()
    assert data1["matched_count"] == 1
    assert data1["preview_source"] == "index"
    assert data1["live_filesystem_verified"] is False
    assert len(data1["items"]) == 1
    assert data1["items"][0]["name"] == "a.txt"
    assert len(data1["roots"]) == 1
    assert data1["roots"][0]["root"] == str(folder.resolve())
    assert data1["roots"][0]["last_indexed_at"] is not None

    # Step 3: Delete a.txt on disk without re-indexing
    file_a.unlink()
    assert not file_a.exists()

    # Step 4: Preview STILL returns a.txt because preview is strictly index-based
    resp2 = client.post(
        "/api/filters/preview",
        json=payload,
        headers={"Origin": "http://testserver"},
    )
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["matched_count"] == 1
    assert data2["preview_source"] == "index"
    assert data2["live_filesystem_verified"] is False
    assert len(data2["items"]) == 1
    assert data2["items"][0]["name"] == "a.txt"

    # Step 5: Re-index root after disk deletion
    index_res2 = service.reindex_root(str(folder))
    assert index_res2["files"] == 0

    # Step 6: Preview reflects updated index and a.txt is gone
    resp3 = client.post(
        "/api/filters/preview",
        json=payload,
        headers={"Origin": "http://testserver"},
    )
    assert resp3.status_code == 200
    data3 = resp3.json()
    assert data3["matched_count"] == 0
    assert len(data3["items"]) == 0
