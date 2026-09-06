import hashlib
import os
from pathlib import Path
from sqlalchemy import select, func
from app.models import (
    BatchPlan,
    BatchPlanItem,
    WorkJob,
    OperationJournal,
    QuarantineEntry,
    IndexRoot,
    IndexedPath,
)
from app.config import Settings
from fastapi.testclient import TestClient
from app.main import create_app
from app.service import FileCenterService

def compute_dir_manifest(root: Path) -> dict[str, tuple[int, str]]:
    manifest = {}
    for p in root.rglob("*"):
        if p.is_file():
            rel = str(p.relative_to(root))
            st = p.stat()
            h = hashlib.sha256(p.read_bytes()).hexdigest()
            manifest[rel] = (st.st_size, h)
    return manifest

def test_filter_preview_strict_zero_mutation(tmp_path: Path):
    data = tmp_path / "data"
    media = data / "media"
    media.mkdir(parents=True, exist_ok=True)
    config = tmp_path / "config"
    config.mkdir(parents=True, exist_ok=True)

    # Populate dummy files on disk
    f1 = media / "movie1.mkv"
    f1.write_bytes(b"dummy movie content")
    f2 = media / "photo1.jpg"
    f2.write_bytes(b"dummy photo content")

    manifest_before = compute_dir_manifest(data)

    settings = Settings(
        config_dir=config,
        data_mount=data,
        allowed_roots_raw=f"{data},{media}",
        allow_mutation=False,  # Enforce mutation disabled
        initial_admin_username="admin",
        initial_admin_password="AdminPassword123!",
    )
    service = FileCenterService(settings)

    # Seed index
    with service.SessionLocal() as session:
        session.add(IndexRoot(root=str(media), last_indexed_at=None))
        session.add(
            IndexedPath(
                root_key=str(media),
                absolute_path=str(f1),
                relative_path="movie1.mkv",
                basename="movie1.mkv",
                stem="movie1",
                suffix=".mkv",
                size=len(f1.read_bytes()),
                mtime_ns=1780000000000000000,
                is_dir=False,
                scan_generation="gen1",
            )
        )
        session.commit()

    app = create_app(settings)
    client = TestClient(app)

    # Login admin
    login_res = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "AdminPassword123!"},
        headers={"Origin": "http://testserver"},
    )
    assert login_res.status_code == 200

    # Capture DB table counts before
    with service.SessionLocal() as session:
        c_plans_before = session.scalar(select(func.count(BatchPlan.id))) or 0
        c_items_before = session.scalar(select(func.count(BatchPlanItem.id))) or 0
        c_jobs_before = session.scalar(select(func.count(WorkJob.id))) or 0
        c_journal_before = session.scalar(select(func.count(OperationJournal.id))) or 0
        c_quarantine_before = session.scalar(select(func.count(QuarantineEntry.id))) or 0

    # Call preview multiple times
    for _ in range(3):
        resp = client.post(
            "/api/filters/preview",
            json={"roots": [str(media)], "page": 1, "page_size": 50},
            headers={"Origin": "http://testserver"},
        )
        assert resp.status_code == 200
        assert resp.json()["matched_count"] == 1

    # Capture DB table counts after
    with service.SessionLocal() as session:
        c_plans_after = session.scalar(select(func.count(BatchPlan.id))) or 0
        c_items_after = session.scalar(select(func.count(BatchPlanItem.id))) or 0
        c_jobs_after = session.scalar(select(func.count(WorkJob.id))) or 0
        c_journal_after = session.scalar(select(func.count(OperationJournal.id))) or 0
        c_quarantine_after = session.scalar(select(func.count(QuarantineEntry.id))) or 0

    # Assert 0 mutations
    assert c_plans_before == c_plans_after == 0
    assert c_items_before == c_items_after == 0
    assert c_jobs_before == c_jobs_after == 0
    assert c_journal_before == c_journal_after == 0
    assert c_quarantine_before == c_quarantine_after == 0

    # Assert filesystem 100% unchanged
    manifest_after = compute_dir_manifest(data)
    assert manifest_before == manifest_after

    # Test that PUT /api/filter-policy succeeds under ALLOW_MUTATION=false without touching filesystem
    policy_resp = client.put(
        "/api/filter-policy",
        json={"exclude_dir_names": [".git", "custom_exclude"]},
        headers={"Origin": "http://testserver"},
    )
    assert policy_resp.status_code == 200
    assert "custom_exclude" in policy_resp.json()["exclude_dir_names"]

    manifest_after_policy = compute_dir_manifest(data)
    assert manifest_before == manifest_after_policy
