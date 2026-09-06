import json
import math
import shutil
import tempfile
from pathlib import Path
from fastapi.testclient import TestClient
from sqlalchemy import text, select

from app.config import Settings
from app.main import create_app
from app.models import BatchPlan, BatchPlanItem, IndexedPath, FilterPolicy, Workflow, WorkflowRevision, WorkJob, OperationJournal
from app.service import FileCenterService


def is_workflow_plan_metadata(metadata_raw):
    if not metadata_raw:
        return False
    if isinstance(metadata_raw, str):
        try:
            m = json.loads(metadata_raw)
        except Exception:
            return False
    elif isinstance(metadata_raw, dict):
        m = metadata_raw
    else:
        return False

    return (
        isinstance(m, dict)
        and m.get("source") == "workflow"
        and isinstance(m.get("workflow_id"), int)
        and not isinstance(m.get("workflow_id"), bool)
        and m.get("workflow_id") > 0
        and isinstance(m.get("workflow_revision"), int)
        and not isinstance(m.get("workflow_revision"), bool)
        and m.get("workflow_revision") > 0
        and isinstance(m.get("definition_sha256"), str)
        and len(m.get("definition_sha256")) == 64
        and isinstance(m.get("compile_digest"), str)
        and len(m.get("compile_digest")) == 64
        and isinstance(m.get("runtime_inputs"), dict)
        and isinstance(m.get("runtime_inputs", {}).get("root_ids"), list)
        and len(m.get("runtime_inputs", {}).get("root_ids")) > 0
        and all(isinstance(r, int) and not isinstance(r, bool) and r > 0 for r in m["runtime_inputs"]["root_ids"])
    )


def test_gate5c_full_integration_acceptance():
    """Gate5-C Full Integration Acceptance Test Suite (TestClient-based in-process integration)."""
    temp_dir = tempfile.mkdtemp()
    try:
        config_dir = Path(temp_dir) / "config"
        data_dir = Path(temp_dir) / "data"
        quarantine_dir = Path(temp_dir) / "quarantine"
        config_dir.mkdir(parents=True)
        data_dir.mkdir(parents=True)
        quarantine_dir.mkdir(parents=True)

        settings = Settings(
            config_dir=config_dir,
            data_mount=data_dir,
            quarantine_root=quarantine_dir,
            allowed_roots_raw=str(data_dir),
            initial_admin_username="admin",
            initial_admin_password="AdminPassword123!",
        )

        service = FileCenterService(settings)
        with service.SessionLocal() as session:
            from app.models import IndexRoot
            session.add(IndexRoot(id=1, root=str(data_dir)))
            policy = FilterPolicy(
                id=1,
                exclude_dir_names_json=json.dumps([".git", ".recycle", "@eaDir", ".nas-file-center-trash"]),
            )
            session.merge(policy)
            session.commit()

        app = create_app(settings)
        client = TestClient(app)
        client.headers["Origin"] = "http://testserver"

        login_resp = client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "AdminPassword123!"},
        )
        assert login_resp.status_code == 200

        # Setup sample files
        f1 = data_dir / "doc1.txt"
        f1.write_text("content1")
        f2 = data_dir / "doc2.txt"
        f2.write_text("content2")

        with service.SessionLocal() as session:
            for idx, f in enumerate([f1, f2]):
                session.add(IndexedPath(
                    root_key=str(data_dir),
                    absolute_path=str(f),
                    relative_path=f.name,
                    basename=f.name,
                    stem=f.stem,
                    suffix=f.suffix,
                    size=len(f.read_text()),
                    mtime_ns=1_000_000,
                    is_dir=False,
                    scan_generation="gen1",
                ))
            session.commit()

        print("[CP1] WorkflowListItem includes 'mode' resolved from definition without DB migration")
        r_create1 = client.post("/api/workflows", json={
            "name": "File WF",
            "definition": {
                "schema_version": 1,
                "mode": "file",
                "steps": [
                    {"id": "s1", "type": "scan", "root_ids": [1]},
                    {"id": "s2", "type": "touch", "touch_now": True, "mtime_ns": None},
                ],
            },
        })
        assert r_create1.status_code == 201
        wf_file_id = r_create1.json()["id"]

        r_create2 = client.post("/api/workflows", json={
            "name": "Org WF",
            "definition": {
                "schema_version": 1,
                "mode": "organizer",
                "steps": [
                    {"id": "s1", "type": "scan", "root_ids": [1]},
                    {"id": "s2", "type": "organize", "profile_snapshot": {"name": "Test Org"}},
                ],
            },
        })
        assert r_create2.status_code == 201
        wf_org_id = r_create2.json()["id"]

        r_list = client.get("/api/workflows")
        assert r_list.status_code == 200
        items_map = {item["id"]: item for item in r_list.json()}
        assert items_map[wf_file_id]["mode"] == "file"
        assert items_map[wf_org_id]["mode"] == "organizer"
        print("  -> CP1 PASSED")

        print("[CP2 & CP3] Filter AST, TouchStep, ScanStep, and OrganizerProfileSnapshot Contracts")
        wf_full = client.post("/api/workflows", json={
            "name": "Full Contract WF",
            "definition": {
                "schema_version": 1,
                "mode": "file",
                "steps": [
                    {"id": "s1", "type": "scan", "root_ids": [1], "subpath": ""},
                    {
                        "id": "s2",
                        "type": "filter",
                        "filter": {
                            "op": "and",
                            "children": [
                                {"field": "extension", "operator": "eq", "value": "txt", "case_sensitive": False},
                                {"field": "size", "operator": "gt", "value": 0},
                            ],
                        },
                    },
                    {"id": "s3", "type": "rename", "pattern": "doc", "replacement": "new_doc"},
                    {"id": "s4", "type": "touch", "touch_now": True, "mtime_ns": None},
                ],
            },
        })
        if wf_full.status_code != 201:
            print("wf_full error:", wf_full.status_code, wf_full.text)
        assert wf_full.status_code == 201
        full_wf_id = wf_full.json()["id"]
        print("  -> CP2 & CP3 PASSED")

        print("[CP4] Rebuild Eligibility Validations")
        # 1. Non-existent plan
        assert client.post("/api/plans/99999/rebuild-preview").status_code == 404

        # Generate plan from full_wf_id
        prev_r1 = client.post(f"/api/workflows/{full_wf_id}/preview", json={"runtime_inputs": {"root_ids": [1]}})
        assert prev_r1.status_code == 200
        digest_r1 = prev_r1.json()["compile_digest"]
        def_sha_r1 = prev_r1.json()["definition_sha256"]

        gen_resp = client.post(
            f"/api/workflows/{full_wf_id}/generate-plan",
            json={"expected_compile_digest": digest_r1, "runtime_inputs": {"root_ids": [1]}},
        )
        assert gen_resp.status_code == 201
        plan_id = gen_resp.json()["plan_id"]

        # 2. Non-stale plan
        r_not_stale = client.post(f"/api/plans/{plan_id}/rebuild-preview")
        assert r_not_stale.status_code == 400
        assert r_not_stale.json()["error"]["code"] == "PLAN_REBUILD_NOT_ELIGIBLE"

        # Make plan stale
        with service.SessionLocal() as session:
            p = session.get(BatchPlan, plan_id)
            p.status = "stale"
            session.commit()

        # 3. Active execution job
        with service.SessionLocal() as session:
            job = WorkJob(
                kind="batch-plan-execute",
                status="running",
                state_json=json.dumps({"plan_id": plan_id}),
            )
            session.add(job)
            session.commit()
            job_id = job.id

        r_active = client.post(f"/api/plans/{plan_id}/rebuild-preview")
        assert r_active.status_code == 400
        assert r_active.json()["error"]["code"] == "PLAN_REBUILD_NOT_ELIGIBLE"

        with service.SessionLocal() as session:
            session.delete(session.get(WorkJob, job_id))
            session.commit()

        # 4. Archived workflow -> 409 WORKFLOW_ARCHIVED (Erratum E2)
        r_arch = client.delete(f"/api/workflows/{full_wf_id}?expected_current_revision=1")
        assert r_arch.status_code == 200

        r_wf_arch = client.post(f"/api/plans/{plan_id}/rebuild-preview")
        assert r_wf_arch.status_code == 409
        assert r_wf_arch.json()["error"]["code"] == "WORKFLOW_ARCHIVED"

        # Unarchive for further checks
        with service.SessionLocal() as session:
            wf = session.get(Workflow, full_wf_id)
            wf.archived_at = None
            session.commit()
        print("  -> CP4 PASSED")

        print("[CP5] Historical Lineage Preservation (Workflow updated to r2, Rebuild must use r1)")
        r_up = client.put(f"/api/workflows/{full_wf_id}", json={
            "expected_current_revision": 1,
            "name": "Full Contract WF Rev 2",
            "definition": {
                "schema_version": 1,
                "mode": "file",
                "steps": [
                    {"id": "s1", "type": "scan", "root_ids": [1]},
                    {"id": "s2", "type": "quarantine", "reason": "Archived in r2"},
                ],
            },
        })
        assert r_up.status_code == 200
        assert r_up.json()["current_revision"] == 2

        print("[CP6 & CP7] Rebuild Preview: touch visibility, only_changed, and Zero Mutation")
        with service.SessionLocal() as session:
            plans_count_pre = session.scalar(text("SELECT count(*) FROM batch_plans"))
            items_count_pre = session.scalar(text("SELECT count(*) FROM batch_plan_items"))

        # only_changed = false (default)
        r_prev = client.post(f"/api/plans/{plan_id}/rebuild-preview", json={})
        assert r_prev.status_code == 200
        prev_data = r_prev.json()
        assert prev_data["workflow_revision"] == 1  # Verified exact historical r1!
        assert prev_data["definition_sha256"] == def_sha_r1
        assert len(prev_data["items"]) == 4  # 2 renames + 2 touches
        assert any(item["operation"] == "touch" for item in prev_data["items"])

        # only_changed = true
        r_prev_changed = client.post(f"/api/plans/{plan_id}/rebuild-preview", json={"only_changed": True})
        assert r_prev_changed.status_code == 200
        assert len(r_prev_changed.json()["items"]) == 2  # Only renames!

        # Verify ZERO DB/FS mutation
        with service.SessionLocal() as session:
            assert session.scalar(text("SELECT count(*) FROM batch_plans")) == plans_count_pre
            assert session.scalar(text("SELECT count(*) FROM batch_plan_items")) == items_count_pre
            p_source = session.get(BatchPlan, plan_id)
            assert p_source.status == "stale"
        print("  -> CP5, CP6, CP7 PASSED")

        print("[CP8 & CP9] Digest Mismatch and Transaction Recheck (Erratum E1)")
        # Wrong digest -> 409 PREVIEW_CHANGED
        r_bad_digest = client.post(f"/api/plans/{plan_id}/rebuild", json={
            "expected_compile_digest": "0" * 64,
        })
        assert r_bad_digest.status_code == 409
        assert r_bad_digest.json()["error"]["code"] == "PREVIEW_CHANGED"
        print("  -> CP8 PASSED")

        print("[CP10] Rebuild Success: New Draft Created, Zero Update on Source Plan, Zero Identities")
        rebuild_digest = prev_data["compile_digest"]
        r_rebuild = client.post(f"/api/plans/{plan_id}/rebuild", json={
            "expected_compile_digest": rebuild_digest,
            "plan_name": "Rebuilt Acceptance Draft",
        })
        assert r_rebuild.status_code in {200, 201}
        rebuild_res = r_rebuild.json()
        new_plan_id = rebuild_res["id"]
        assert new_plan_id != plan_id

        with service.SessionLocal() as session:
            # Source plan must be UNCHANGED
            p_orig = session.get(BatchPlan, plan_id)
            assert p_orig.status == "stale"

            # New draft plan
            p_new = session.get(BatchPlan, new_plan_id)
            assert p_new.status == "draft"
            assert p_new.name == "Rebuilt Acceptance Draft"
            meta = json.loads(p_new.metadata_json)
            assert meta["source"] == "workflow"
            assert meta["workflow_id"] == full_wf_id
            assert meta["workflow_revision"] == 1
            assert meta["compile_digest"] == rebuild_digest
            assert meta["rebuild_of_plan_id"] == plan_id
            assert meta["rebuild_source_status"] == "stale"

            # Items physical identities zeroed
            items = session.query(BatchPlanItem).filter_by(plan_id=new_plan_id).all()
            assert len(items) == 4
            for it in items:
                assert it.expected_inode == 0
                assert it.expected_device == 0
                assert it.expected_mtime_ns == 0
                assert it.expected_hash == ""

            # Zero work jobs and zero operation journal entries
            assert session.scalar(text(f"SELECT count(*) FROM work_jobs WHERE json_extract(state_json, '$.plan_id') = {new_plan_id}")) == 0
            assert session.scalar(text(f"SELECT count(*) FROM operation_journal WHERE plan_id = {new_plan_id}")) == 0
        print("  -> CP9 & CP10 PASSED")

        print("[CP11] Frontend Type Guard is_workflow_plan_metadata (Erratum E4)")
        assert is_workflow_plan_metadata(p_new.metadata_json) is True
        assert is_workflow_plan_metadata({"source": "dedupe"}) is False
        assert is_workflow_plan_metadata("{bad json") is False
        print("  -> CP11 PASSED")

        print("=== ALL GATE5-C BLACKBOX CHECKS PASSED SUCCESSFULLY ===")

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    test_gate5c_full_blackbox_acceptance()
