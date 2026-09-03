from __future__ import annotations

from pathlib import Path
from fastapi.testclient import TestClient
import pytest

from app.config import Settings
from app.main import create_app


def test_organizer_api_contract_and_plan_generation(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    config = tmp_path / "config"
    config.mkdir()

    root = data / "少女映画"
    root.mkdir()

    # Folder 1: Needs rename (outdated suffix 9P -> 2P 1V)
    folder1 = root / "001 少女映画 桜木 [9P 1GB]"
    folder1.mkdir()
    (folder1 / "img1.jpg").write_bytes(b"image1_data_1234")
    (folder1 / "img2.png").write_bytes(b"image2_data_5678")
    (folder1 / "video1.mp4").write_bytes(b"video1_data_9012")

    # Folder 2: Suspicious tag folder [存疑]
    folder2 = root / "002 少女映画 結衣 [存疑]"
    folder2.mkdir()
    (folder2 / "photo.jpg").write_bytes(b"photo_data")

    # Folder 3: Already normalized folder (correct stats 1P 10.0B)
    folder3 = root / "003 少女映画 美咲 [1P 0.0MB]"
    folder3.mkdir()
    (folder3 / "pic.jpg").write_bytes(b"0123456789")

    settings = Settings(
        config_dir=config,
        data_mount=data,
        allowed_roots_raw=str(data),
        allow_mutation=True,
        allow_delete=False,
        initial_admin_username="admin",
        initial_admin_password="AdminPassword123!",
    )
    client = TestClient(create_app(settings))
    client.headers.update({"Origin": "http://testserver"})
    client.post("/api/auth/login", json={"username": "admin", "password": "AdminPassword123!"})

    # 1. Test /api/organizers/shaonv/preview
    resp = client.post("/api/organizers/shaonv/preview", json={"root": str(root)})
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 3

    # Find each item by source name
    item1 = next(i for i in items if "001" in i["source"])
    assert item1["images"] == 2
    assert item1["videos"] == 1
    assert item1["total_bytes"] > 0
    assert item1["has_suspicious_tag"] is False
    assert item1["changed"] is True
    assert "2P 1V" in item1["target"]

    item2 = next(i for i in items if "002" in i["source"])
    assert item2["images"] == 1
    assert item2["videos"] == 0
    assert item2["has_suspicious_tag"] is True
    assert item2["changed"] is True
    assert "[存疑]" in item2["target"]
    assert "1P" in item2["target"]

    item3 = next(i for i in items if "003" in i["source"])
    assert item3["images"] == 1
    assert item3["videos"] == 0
    assert item3["has_suspicious_tag"] is False
    assert item3["changed"] is False
    assert item3["source"] == item3["target"]

    # 2. Generate Rename Plan from changed items
    plan_items = [
        {"operation": "rename", "source": i["source"], "target": i["target"]}
        for i in items if i["changed"]
    ]
    assert len(plan_items) == 2

    plan_resp = client.post(
        "/api/plans",
        json={
            "name": "Organizer Rename Plan",
            "kind": "organizer-shaonv",
            "items": plan_items,
        },
    )
    assert plan_resp.status_code == 200
    plan_id = plan_resp.json()["id"]

    # 3. Freeze -> Validate -> Execute
    client.post(f"/api/plans/{plan_id}/freeze")
    val_resp = client.post(f"/api/plans/{plan_id}/validate")
    assert val_resp.json()["status"] == "ready"

    exec_resp = client.post(f"/api/plans/{plan_id}/execute")
    assert exec_resp.status_code == 200
    assert exec_resp.json()["status"] == "completed"

    # Verify folders were renamed
    assert not folder1.exists()
    assert Path(item1["target"]).exists()
    assert not folder2.exists()
    assert Path(item2["target"]).exists()
    assert folder3.exists()
