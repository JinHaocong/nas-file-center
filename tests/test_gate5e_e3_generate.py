import os
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, func

from app.main import create_app
from app.models import Base, IndexRoot, IndexedPath, BatchPlan, BatchPlanItem, WorkJob, QuarantineEntry
from app.config import Settings
from app.service import FileCenterService
from app.auth.password import hash_password
from app.models import User

@pytest.fixture
def api_test_env(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    quarantine_dir = tmp_path / "quarantine"
    quarantine_dir.mkdir()

    db_path = config_dir / "app.db"
    settings = Settings(
        config_dir=config_dir,
        reports_dir=tmp_path / "reports",
        backups_dir=tmp_path / "backups",
        logs_dir=tmp_path / "logs",
        fclones_home=tmp_path / "fclones",
        database_path=db_path,
        allowed_roots_raw=str(data_dir),
        quarantine_root=quarantine_dir,
        protect_last_file=True,
    )

    service = FileCenterService(settings)

    root1_path = data_dir / "root1"
    root1_path.mkdir()

    with service.SessionLocal() as session:
        r = IndexRoot(id=1, root=str(root1_path))
        session.add(r)
        session.commit()
        reg_user = User(
            username="normaluser",
            password_hash=hash_password("UserPassword123!"),
            is_active=True,
            role="user",
        )
        session.add(reg_user)
        session.commit()

    app = create_app(settings)
    client = TestClient(app)
    client.headers["Origin"] = "http://testserver"
    login_resp = client.post(
        "/api/auth/login",
        json={"username": "normaluser", "password": "UserPassword123!"},
    )
    assert login_resp.status_code == 200

    return {
        "service": service,
        "settings": settings,
        "client": client,
        "data_dir": data_dir,
        "root1_path": root1_path,
    }
import pytest
from app.models import BatchPlan, BatchPlanItem

def test_generate_flatten_one_level_success(api_test_env):
    client = api_test_env["client"]
    service = api_test_env["service"]
    root = api_test_env["root1_path"]
    wrapper = root / "wrapper"
    wrapper.mkdir()
    (wrapper / "a.txt").write_text("a")
    
    action = {
        "type": "flatten_one_level",
        "wrapper_paths": [str(wrapper)]
    }
    
    resp = client.post("/api/batch-utilities/preview", json={"action": action, "page": 1, "page_size": 50})
    assert resp.status_code == 200
    preview_digest = resp.json()["preview_digest"]
    
    req = {
        "action": action,
        "expected_preview_digest": preview_digest
    }
    resp = client.post("/api/batch-utilities/generate-plan", json=req)
    assert resp.status_code == 201, resp.text
    
    data = resp.json()
    plan_id = data["id"]
    
    with service.SessionLocal() as session:
        plan = session.get(BatchPlan, plan_id)
        
        
        items = session.query(BatchPlanItem).filter_by(plan_id=plan_id).all()
        assert len(items) == 1
        assert items[0].operation == "move"
        assert items[0].source_path == str(wrapper / "a.txt")
        assert items[0].expected_hash is None


def test_generate_e3_draft_physical_identity_ownership(api_test_env):
    client = api_test_env["client"]
    service = api_test_env["service"]
    root = api_test_env["root1_path"]
    wrapper = root / "wrapper_ident"
    wrapper.mkdir()
    f = wrapper / "a.txt"
    f.write_text("hello identity")
    st = f.stat()
    
    action = {
        "type": "flatten_one_level",
        "wrapper_paths": [str(wrapper)]
    }
    resp = client.post("/api/batch-utilities/preview", json={"action": action})
    assert resp.status_code == 200
    digest = resp.json()["preview_digest"]
    
    resp = client.post("/api/batch-utilities/generate-plan", json={"action": action, "expected_preview_digest": digest})
    assert resp.status_code == 201
    plan_id = resp.json()["id"]
    
    # 1. Inspect BatchPlanItem before Freeze
    with service.SessionLocal() as session:
        items = session.query(BatchPlanItem).filter_by(plan_id=plan_id).all()
        assert len(items) == 1
        assert items[0].expected_device == 0
        assert items[0].expected_inode == 0
        assert items[0].expected_mtime_ns == 0
        assert items[0].expected_hash is None
        
    # 2. Freeze and inspect physical identity captured
    service.freeze_plan(plan_id)
    with service.SessionLocal() as session:
        items = session.query(BatchPlanItem).filter_by(plan_id=plan_id).all()
        assert len(items) == 1
        assert items[0].expected_device == st.st_dev
        assert items[0].expected_inode == st.st_ino
        assert items[0].expected_mtime_ns == st.st_mtime_ns

def test_generate_flatten_one_level_preview_changed(api_test_env):
    client = api_test_env["client"]
    root = api_test_env["root1_path"]
    wrapper = root / "wrapper"
    wrapper.mkdir()
    (wrapper / "a.txt").write_text("a")
    
    action = {
        "type": "flatten_one_level",
        "wrapper_paths": [str(wrapper)]
    }
    
    req = {
        "action": action,
        "expected_preview_digest": "0" * 64
    }
    resp = client.post("/api/batch-utilities/generate-plan", json=req)
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "PREVIEW_CHANGED"

def test_generate_flatten_one_level_conflict(api_test_env):
    client = api_test_env["client"]
    root = api_test_env["root1_path"]
    wrapper = root / "wrapper"
    wrapper.mkdir()
    (wrapper / "a.txt").write_text("a")
    # Conflict: target exists
    (root / "a.txt").write_text("exists")
    
    action = {
        "type": "flatten_one_level",
        "wrapper_paths": [str(wrapper)]
    }
    
    resp = client.post("/api/batch-utilities/preview", json={"action": action})
    assert resp.status_code == 200
    preview_digest = resp.json()["preview_digest"]
    
    req = {
        "action": action,
        "expected_preview_digest": preview_digest
    }
    resp = client.post("/api/batch-utilities/generate-plan", json=req)
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "BATCH_UTILITY_COLLISION"

def test_generate_flatten_one_level_empty_plan(api_test_env):
    client = api_test_env["client"]
    root = api_test_env["root1_path"]
    wrapper = root / "wrapper"
    wrapper.mkdir()
    
    action = {
        "type": "flatten_one_level",
        "wrapper_paths": [str(wrapper)]
    }
    
    resp = client.post("/api/batch-utilities/preview", json={"action": action})
    assert resp.status_code == 200
    preview_digest = resp.json()["preview_digest"]
    
    req = {
        "action": action,
        "expected_preview_digest": preview_digest
    }
    resp = client.post("/api/batch-utilities/generate-plan", json=req)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "BATCH_UTILITY_EMPTY_PLAN"


def test_generate_flatten_mixed_safe_and_blocked_fails_closed(api_test_env):
    client = api_test_env["client"]
    service = api_test_env["service"]
    root = api_test_env["root1_path"]
    wrapper = root / "wrapper_mixed"
    wrapper.mkdir()
    (wrapper / "blocked.txt").write_text("blocked")
    (wrapper / "safe.txt").write_text("safe")
    # Make target for blocked exist
    (root / "blocked.txt").write_text("exists")
    
    action = {
        "type": "flatten_one_level",
        "wrapper_paths": [str(wrapper)]
    }
    
    resp = client.post("/api/batch-utilities/preview", json={"action": action})
    assert resp.status_code == 200
    assert resp.json()["planned_operations_count"] == 1
    preview_digest = resp.json()["preview_digest"]
    
    req = {
        "action": action,
        "expected_preview_digest": preview_digest
    }
    resp = client.post("/api/batch-utilities/generate-plan", json=req)
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "BATCH_UTILITY_COLLISION"
    
    # Verify zero plans created
    with service.SessionLocal() as session:
        plans = session.query(BatchPlan).all()
        assert len(plans) == 0


def test_generate_flatten_symlink_fails_closed(api_test_env):
    import os
    client = api_test_env["client"]
    service = api_test_env["service"]
    root = api_test_env["root1_path"]
    wrapper = root / "wrapper_sym_child_gen"
    wrapper.mkdir()
    (wrapper / "real.txt").write_text("real")
    os.symlink("real.txt", wrapper / "child.link")
    
    action = {
        "type": "flatten_one_level",
        "wrapper_paths": [str(wrapper)]
    }
    
    resp = client.post("/api/batch-utilities/preview", json={"action": action})
    assert resp.status_code == 200
    preview_digest = resp.json()["preview_digest"]
    
    req = {
        "action": action,
        "expected_preview_digest": preview_digest
    }
    resp = client.post("/api/batch-utilities/generate-plan", json=req)
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "BATCH_UTILITY_SYMLINK_BLOCKED"
    
    with service.SessionLocal() as session:
        plans = session.query(BatchPlan).all()
        assert len(plans) == 0


def test_generate_flatten_source_outside_allowed_roots_raises_cross_root(api_test_env, tmp_path):
    from unittest.mock import patch
    from app.batch_utilities.flatten import FlattenCandidate
    client = api_test_env["client"]
    service = api_test_env["service"]
    root = api_test_env["root1_path"]
    wrapper = root / "wrapper_cross_src"
    wrapper.mkdir()
    
    outside = tmp_path / "outside_secret"
    outside.mkdir()
    outside_f = outside / "secret.txt"
    outside_f.write_text("secret")
    
    action = {
        "type": "flatten_one_level",
        "wrapper_paths": [str(wrapper)]
    }
    
    cand = FlattenCandidate(
        wrapper_path=str(wrapper),
        source_path=str(outside_f),
        target_path=str(root / "secret.txt"),
        object_type="file",
        size=6,
        mtime_ns=0,
        device=0,
        inode=0,
        is_dir=False,
    )
    
    with patch("app.batch_utilities.compiler.discover_flatten_one_level", return_value=([cand], [])):
        resp = client.post("/api/batch-utilities/preview", json={"action": action})
        assert resp.status_code == 200
        preview_digest = resp.json()["preview_digest"]
        
        req = {
            "action": action,
            "expected_preview_digest": preview_digest
        }
        resp = client.post("/api/batch-utilities/generate-plan", json=req)
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "BATCH_UTILITY_CROSS_ROOT"
        
        with service.SessionLocal() as session:
            plans = session.query(BatchPlan).all()
            assert len(plans) == 0


def test_generate_flatten_source_missing_race_raises_409(api_test_env):
    """Test D: Generate Phase A with a racing discovery where source disappears before graph resolution.
    Expected: 409 structured blocking response, 0 Draft.
    """
    from unittest.mock import patch
    from app.batch_utilities.flatten import discover_flatten_one_level
    client = api_test_env["client"]
    service = api_test_env["service"]
    root = api_test_env["root1_path"]
    wrapper = root / "racing_w"
    wrapper.mkdir()
    gone_file = wrapper / "gone.txt"
    gone_file.write_text("temporary")

    action = {
        "type": "flatten_one_level",
        "wrapper_paths": [str(wrapper)]
    }

    # Real discovery observes gone.txt
    cands, errs = discover_flatten_one_level(wrapper_paths=[str(wrapper)])
    assert len(cands) == 1

    # Source disappears before graph resolution
    gone_file.unlink()

    # Generate Phase A with racing discovery where source disappeared before graph resolution
    with patch("app.batch_utilities.compiler.discover_flatten_one_level", return_value=(cands, errs)):
        resp_prev = client.post("/api/batch-utilities/preview", json={"action": action})
        assert resp_prev.status_code == 200
        preview_digest = resp_prev.json()["preview_digest"]

        req = {
            "action": action,
            "expected_preview_digest": preview_digest
        }
        resp = client.post("/api/batch-utilities/generate-plan", json=req)
        assert resp.status_code == 409
        err = resp.json()["error"]
        assert err["code"] == "BATCH_UTILITY_CONFLICT"
        assert err["details"]["blocking_conflict_count"] == 1
        conflicts = err["details"]["conflicts"]
        assert len(conflicts) == 1
        assert conflicts[0]["source_path"] == str(gone_file)
        assert conflicts[0]["reason_code"] == "SOURCE_MISSING"

        with service.SessionLocal() as session:
            plans = session.query(BatchPlan).all()
            assert len(plans) == 0


def test_generate_flatten_same_type_source_replacement_race_raises_409(api_test_env):
    """Section 7 API regression:
    1. Preview old file normally (W/same.bin, regular file, size=4, content=AAAA).
    2. During Generate: replace source after discovery but before graph (content=BBBB, size=4, different identity).
    Expected: HTTP 409 PREVIEW_CHANGED, 0 Draft.
    """
    import os
    from unittest.mock import patch
    from app.batch_utilities import compiler as compiler_module

    client = api_test_env["client"]
    service = api_test_env["service"]
    root = api_test_env["root1_path"]
    wrapper = root / "w_same_type_race"
    wrapper.mkdir()
    same_bin = wrapper / "same.bin"
    same_bin.write_bytes(b"AAAA")  # size = 4

    action = {
        "type": "flatten_one_level",
        "wrapper_paths": [str(wrapper)]
    }

    # 1. Preview old file normally
    resp_prev = client.post("/api/batch-utilities/preview", json={"action": action})
    assert resp_prev.status_code == 200
    preview_digest = resp_prev.json()["preview_digest"]

    # 2. Race hook: during Generate Phase A, discovery observes the original source,
    # then immediately before graph resolution, same.bin is replaced by another regular file (BBBB, size 4)
    orig_discover = compiler_module.discover_flatten_one_level

    def racing_discover(wrapper_paths, *args, **kwargs):
        cands, errs = orig_discover(wrapper_paths, *args, **kwargs)
        # File is replaced after discovery but before graph resolution
        same_bin.unlink()
        same_bin.write_bytes(b"BBBB")
        new_mtime = cands[0].mtime_ns + 5_000_000
        os.utime(same_bin, ns=(new_mtime, new_mtime))
        return cands, errs

    with patch("app.batch_utilities.compiler.discover_flatten_one_level", side_effect=racing_discover):
        req = {
            "action": action,
            "expected_preview_digest": preview_digest
        }
        resp = client.post("/api/batch-utilities/generate-plan", json=req)
        assert resp.status_code == 409
        err = resp.json()["error"]
        assert err["code"] == "PREVIEW_CHANGED"

        # Verify zero Draft plans created in DB
        with service.SessionLocal() as session:
            plans = session.query(BatchPlan).all()
            assert len(plans) == 0


def test_generate_flatten_wrapper_symlink_swap_race_raises_409(api_test_env):
    """Section 8 API regression:
    Preview: W is normal directory.
    During Generate:
    after discovery / wrapper identity observation and before graph,
    replace W with symlink to another directory inside the SAME allowed root.
    Expected: HTTP 409 PREVIEW_CHANGED, 0 Draft.
    """
    import os
    import shutil
    from unittest.mock import patch
    from app.batch_utilities import compiler as compiler_module

    client = api_test_env["client"]
    service = api_test_env["service"]
    root = api_test_env["root1_path"]
    wrapper = root / "w_symlink_race"
    wrapper.mkdir()
    (wrapper / "a.txt").write_text("file in W")

    other = root / "other_dir"
    other.mkdir()
    (other / "a.txt").write_text("file in other")

    action = {
        "type": "flatten_one_level",
        "wrapper_paths": [str(wrapper)]
    }

    # 1. Preview W normally
    resp_prev = client.post("/api/batch-utilities/preview", json={"action": action})
    assert resp_prev.status_code == 200
    preview_digest = resp_prev.json()["preview_digest"]

    # 2. Race hook: after discovery / wrapper observation but before graph, replace W with W -> other
    orig_discover = compiler_module.discover_flatten_one_level

    def racing_discover(wrapper_paths, *args, **kwargs):
        cands, errs = orig_discover(wrapper_paths, *args, **kwargs)
        shutil.rmtree(wrapper)
        os.symlink(str(other), str(wrapper))
        return cands, errs

    with patch("app.batch_utilities.compiler.discover_flatten_one_level", side_effect=racing_discover):
        req = {
            "action": action,
            "expected_preview_digest": preview_digest
        }
        resp = client.post("/api/batch-utilities/generate-plan", json=req)
        assert resp.status_code == 409
        err = resp.json()["error"]
        assert err["code"] == "PREVIEW_CHANGED"

        # Verify zero Draft plans and zero items created in DB
        with service.SessionLocal() as session:
            plans = session.query(BatchPlan).all()
            assert len(plans) == 0


def test_generate_flatten_wrapper_replaced_by_different_directory_race_raises_409(api_test_env):
    """Section 8 additional API regression:
    Wrapper replaced by a different real directory identity (new inode).
    Expected: HTTP 409 PREVIEW_CHANGED, 0 Draft.
    """
    import shutil
    from unittest.mock import patch
    from app.batch_utilities import compiler as compiler_module

    client = api_test_env["client"]
    service = api_test_env["service"]
    root = api_test_env["root1_path"]
    wrapper = root / "w_replaced_dir_race"
    wrapper.mkdir()
    (wrapper / "a.txt").write_text("file in W")

    action = {
        "type": "flatten_one_level",
        "wrapper_paths": [str(wrapper)]
    }

    resp_prev = client.post("/api/batch-utilities/preview", json={"action": action})
    assert resp_prev.status_code == 200
    preview_digest = resp_prev.json()["preview_digest"]

    import os
    orig_discover = compiler_module.discover_flatten_one_level

    def racing_discover(wrapper_paths, *args, **kwargs):
        cands, errs = orig_discover(wrapper_paths, *args, **kwargs)
        w2 = root / "w_new"
        w2.mkdir()
        (w2 / "a.txt").write_text("file in new W")
        shutil.rmtree(wrapper)
        os.rename(str(w2), str(wrapper))
        return cands, errs

    with patch("app.batch_utilities.compiler.discover_flatten_one_level", side_effect=racing_discover):
        req = {
            "action": action,
            "expected_preview_digest": preview_digest
        }
        resp = client.post("/api/batch-utilities/generate-plan", json=req)
        assert resp.status_code == 409
        err = resp.json()["error"]
        assert err["code"] == "PREVIEW_CHANGED"

        with service.SessionLocal() as session:
            plans = session.query(BatchPlan).all()
            assert len(plans) == 0


def test_generate_flatten_nonempty_wrapper_child_appearance_race_raises_409(api_test_env):
    """E3-hotfix5 API Regression 1:
    Nonempty wrapper child-appearance race.
    1. wrapper contains W/a.txt
    2. preview: candidate_count = 1, planned_operations_count = 1
    3. during Generate Phase A: after discovery & wrapper observation, before graph authority:
       create W/new.txt
    Expected: HTTP 409 PREVIEW_CHANGED, 0 Draft.
    """
    from unittest.mock import patch
    from app.batch_utilities import flatten_graph as flatten_graph_module

    client = api_test_env["client"]
    service = api_test_env["service"]
    root = api_test_env["root1_path"]
    wrapper = root / "w_nonempty_child_race"
    wrapper.mkdir()
    (wrapper / "a.txt").write_text("file in W")

    action = {
        "type": "flatten_one_level",
        "wrapper_paths": [str(wrapper)]
    }

    resp_prev = client.post("/api/batch-utilities/preview", json={"action": action})
    assert resp_prev.status_code == 200
    preview_digest = resp_prev.json()["preview_digest"]

    orig_resolve_graph = flatten_graph_module.resolve_flatten_graph

    def racing_resolve_graph(*args, **kwargs):
        # Create W/new.txt after discovery & wrapper observation, before graph
        (wrapper / "new.txt").write_text("new file appeared")
        return orig_resolve_graph(*args, **kwargs)

    with patch("app.batch_utilities.compiler.resolve_flatten_graph", side_effect=racing_resolve_graph):
        req = {
            "action": action,
            "expected_preview_digest": preview_digest
        }
        resp = client.post("/api/batch-utilities/generate-plan", json=req)
        assert resp.status_code == 409
        err = resp.json()["error"]
        assert err["code"] == "PREVIEW_CHANGED"

        with service.SessionLocal() as session:
            plans = session.query(BatchPlan).all()
            assert len(plans) == 0


def test_generate_flatten_empty_wrapper_child_appearance_race_raises_409(api_test_env):
    """E3-hotfix5 API Regression 2:
    Empty wrapper child-appearance race.
    1. wrapper W is initially empty (0 candidates, 0 planned ops)
    2. preview: candidate_count = 0, planned_operations_count = 0
    3. during Generate Phase A: after discovery & wrapper observation, before graph authority:
       create W/new.txt
    Expected: HTTP 409 PREVIEW_CHANGED (NOT 422 BATCH_UTILITY_EMPTY_PLAN), 0 Draft.
    """
    from unittest.mock import patch
    from app.batch_utilities import flatten_graph as flatten_graph_module

    client = api_test_env["client"]
    service = api_test_env["service"]
    root = api_test_env["root1_path"]
    wrapper = root / "w_empty_child_race"
    wrapper.mkdir()

    action = {
        "type": "flatten_one_level",
        "wrapper_paths": [str(wrapper)]
    }

    resp_prev = client.post("/api/batch-utilities/preview", json={"action": action})
    assert resp_prev.status_code == 200
    preview_digest = resp_prev.json()["preview_digest"]

    orig_resolve_graph = flatten_graph_module.resolve_flatten_graph

    def racing_resolve_graph(*args, **kwargs):
        # Create W/new.txt in empty wrapper after discovery & wrapper observation, before graph
        (wrapper / "new.txt").write_text("new file appeared in empty wrapper")
        return orig_resolve_graph(*args, **kwargs)

    with patch("app.batch_utilities.compiler.resolve_flatten_graph", side_effect=racing_resolve_graph):
        req = {
            "action": action,
            "expected_preview_digest": preview_digest
        }
        resp = client.post("/api/batch-utilities/generate-plan", json=req)
        assert resp.status_code == 409
        err = resp.json()["error"]
        assert err["code"] == "PREVIEW_CHANGED"

        with service.SessionLocal() as session:
            plans = session.query(BatchPlan).all()
            assert len(plans) == 0


def test_generate_continuity_scandir_failure_empty_wrapper(api_test_env):
    """E3-hotfix6 Regression:
    Empty wrapper continuity re-scan failure during Generate Phase A.
    Expected: HTTP 422 BATCH_UTILITY_INVALID_CONFIG (NOT 409 PREVIEW_CHANGED or 200/201),
              details: stage=CONTINUITY, errno=13, wrapper_path.
              Zero draft plans in DB.
    """
    import os
    from unittest.mock import patch
    client = api_test_env["client"]
    service = api_test_env["service"]
    root = api_test_env["root1_path"]
    wrapper = root / "w_empty_cont_err"
    wrapper.mkdir()

    action = {
        "type": "flatten_one_level",
        "wrapper_paths": [str(wrapper)]
    }

    resp_prev = client.post("/api/batch-utilities/preview", json={"action": action})
    assert resp_prev.status_code == 200
    preview_digest = resp_prev.json()["preview_digest"]

    orig_scandir = os.scandir
    call_count = 0

    def mock_scandir(path, *args, **kwargs):
        nonlocal call_count
        if os.path.normpath(str(path)) == str(wrapper):
            call_count += 1
            if call_count == 3:
                err = PermissionError(13, "Permission denied")
                err.errno = 13
                raise err
        return orig_scandir(path, *args, **kwargs)

    with patch("os.scandir", side_effect=mock_scandir):
        req = {
            "action": action,
            "expected_preview_digest": preview_digest
        }
        resp = client.post("/api/batch-utilities/generate-plan", json=req)
        assert resp.status_code == 422
        err = resp.json()["error"]
        assert err["code"] == "BATCH_UTILITY_INVALID_CONFIG"
        assert err["details"].get("wrapper_path") == str(wrapper)
        assert err["details"].get("errno") == 13
        assert err["details"].get("stage") == "CONTINUITY"

        with service.SessionLocal() as session:
            plans = session.query(BatchPlan).all()
            assert len(plans) == 0


def test_generate_continuity_scandir_failure_nonempty_wrapper(api_test_env):
    """E3-hotfix6 Regression:
    Nonempty wrapper continuity re-scan failure during Generate Phase A.
    Expected: HTTP 422 BATCH_UTILITY_INVALID_CONFIG,
              details: stage=CONTINUITY, errno=13, wrapper_path.
              Zero draft plans in DB.
    """
    import os
    from unittest.mock import patch
    client = api_test_env["client"]
    service = api_test_env["service"]
    root = api_test_env["root1_path"]
    wrapper = root / "w_nonempty_cont_err"
    wrapper.mkdir()
    (wrapper / "item.txt").write_text("data")

    action = {
        "type": "flatten_one_level",
        "wrapper_paths": [str(wrapper)]
    }

    resp_prev = client.post("/api/batch-utilities/preview", json={"action": action})
    assert resp_prev.status_code == 200
    preview_digest = resp_prev.json()["preview_digest"]

    orig_scandir = os.scandir
    call_count = 0

    def mock_scandir(path, *args, **kwargs):
        nonlocal call_count
        if os.path.normpath(str(path)) == str(wrapper):
            call_count += 1
            if call_count == 3:
                err = PermissionError(13, "Permission denied")
                err.errno = 13
                raise err
        return orig_scandir(path, *args, **kwargs)

    with patch("os.scandir", side_effect=mock_scandir):
        req = {
            "action": action,
            "expected_preview_digest": preview_digest
        }
        resp = client.post("/api/batch-utilities/generate-plan", json=req)
        assert resp.status_code == 422
        err = resp.json()["error"]
        assert err["code"] == "BATCH_UTILITY_INVALID_CONFIG"
        assert err["details"].get("wrapper_path") == str(wrapper)
        assert err["details"].get("errno") == 13
        assert err["details"].get("stage") == "CONTINUITY"

        with service.SessionLocal() as session:
            plans = session.query(BatchPlan).all()
            assert len(plans) == 0


def test_generate_canonical_wrapper_plan_metadata(api_test_env):
    """E3-hotfix6 Regression:
    Wrapper path provided with trailing slash 'W/' is saved as canonical 'W'
    in plan_metadata top-level wrapper_paths and canonical_action_config.
    db_lineage_digest is None.
    """
    import json
    client = api_test_env["client"]
    service = api_test_env["service"]
    root = api_test_env["root1_path"]
    wrapper = root / "w_meta_canon"
    wrapper.mkdir()
    (wrapper / "item.txt").write_text("content")

    action = {
        "type": "flatten_one_level",
        "wrapper_paths": [str(wrapper) + "/"]
    }

    resp_prev = client.post("/api/batch-utilities/preview", json={"action": action})
    assert resp_prev.status_code == 200
    preview_digest = resp_prev.json()["preview_digest"]

    req = {
        "action": action,
        "expected_preview_digest": preview_digest
    }
    resp_gen = client.post("/api/batch-utilities/generate-plan", json=req)
    assert resp_gen.status_code == 201

    with service.SessionLocal() as session:
        plans = session.query(BatchPlan).all()
        assert len(plans) == 1
        plan = plans[0]
        meta = json.loads(plan.metadata_json)
        assert meta["wrapper_paths"] == [str(wrapper)]
        assert meta["canonical_action_config"]["wrapper_paths"] == [str(wrapper)]
        assert meta.get("db_lineage_digest") is None


def test_generate_canonical_wrapper_symlink_dotdot_selection(api_test_env):
    """E3-hotfix7 Regression:
    Generate creates draft move intents from the actual physical directory
    selected via symlink-sensitive dotdot traversal.
    """
    import os
    import json
    from app.models import BatchPlan
    client = api_test_env["client"]
    service = api_test_env["service"]
    root = api_test_env["root1_path"]

    a_dir = root / "A"
    b_dir = a_dir / "B"
    b_dir.mkdir(parents=True)
    w_intended = a_dir / "W"
    w_intended.mkdir(parents=True)
    (w_intended / "intended.txt").write_text("intended")

    w_wrong = root / "W"
    w_wrong.mkdir(parents=True)
    (w_wrong / "wrong.txt").write_text("wrong")

    link = root / "link"
    os.symlink(str(b_dir), str(link))

    wrapper_input = str(link) + "/../W"

    action = {
        "type": "flatten_one_level",
        "wrapper_paths": [wrapper_input],
    }

    resp_prev = client.post("/api/batch-utilities/preview", json={"action": action})
    assert resp_prev.status_code == 200
    preview_digest = resp_prev.json()["preview_digest"]

    req = {
        "action": action,
        "expected_preview_digest": preview_digest,
    }
    resp_gen = client.post("/api/batch-utilities/generate-plan", json=req)
    assert resp_gen.status_code == 201

    with service.SessionLocal() as session:
        plans = session.query(BatchPlan).all()
        assert len(plans) == 1
        plan = plans[0]
        meta = json.loads(plan.metadata_json)
        assert meta["wrapper_paths"] == [str(w_intended.resolve(strict=True))]
        assert meta["canonical_action_config"]["wrapper_paths"] == [str(w_intended.resolve(strict=True))]

        items = plan.items
        assert len(items) == 1
        item = items[0]
        assert item.source_path == str(w_intended.resolve(strict=True) / "intended.txt")
        assert item.target_path == str(a_dir.resolve(strict=True) / "intended.txt")


def test_generate_canonical_wrapper_trailing_space_directory(api_test_env):
    """E3-hotfix7 Regression:
    Generate creates draft move intents from the valid trailing-space directory.
    """
    import json
    from app.models import BatchPlan
    client = api_test_env["client"]
    service = api_test_env["service"]
    root = api_test_env["root1_path"]

    w_wrong = root / "W"
    w_wrong.mkdir(parents=True)
    (w_wrong / "wrong.txt").write_text("wrong")

    w_space = root / "W "
    w_space.mkdir(parents=True)
    (w_space / "intended.txt").write_text("intended")

    wrapper_input = str(w_space)
    assert wrapper_input.endswith("W ")

    action = {
        "type": "flatten_one_level",
        "wrapper_paths": [wrapper_input],
    }

    resp_prev = client.post("/api/batch-utilities/preview", json={"action": action})
    assert resp_prev.status_code == 200
    preview_digest = resp_prev.json()["preview_digest"]

    req = {
        "action": action,
        "expected_preview_digest": preview_digest,
    }
    resp_gen = client.post("/api/batch-utilities/generate-plan", json=req)
    assert resp_gen.status_code == 201

    with service.SessionLocal() as session:
        plans = session.query(BatchPlan).all()
        assert len(plans) == 1
        plan = plans[0]
        meta = json.loads(plan.metadata_json)
        assert meta["wrapper_paths"] == [str(w_space.resolve(strict=True))]
        assert meta["wrapper_paths"][0].endswith("W ")

        items = plan.items
        assert len(items) == 1
        item = items[0]
        assert item.source_path == str(w_space.resolve(strict=True) / "intended.txt")


def test_generate_symlink_sensitive_trailing_slash_leaf_symlink_blocked(api_test_env):
    """E3-hotfix8 Regression A:
    Generate rejects trailing-slash leaf symlink wrapper:
    root/link/../W/ where root/A/W is a symlink.
    Expected: HTTP 409 BATCH_UTILITY_SYMLINK_BLOCKED. 0 Draft plans in DB.
    """
    import os
    from app.models import BatchPlan
    client = api_test_env["client"]
    service = api_test_env["service"]
    root = api_test_env["root1_path"]

    a_dir = root / "A"
    b_dir = a_dir / "B"
    b_dir.mkdir(parents=True)
    real_dir = a_dir / "Real"
    real_dir.mkdir(parents=True)
    (real_dir / "secret.txt").write_text("secret")

    w_symlink = a_dir / "W"
    os.symlink(str(real_dir), str(w_symlink))

    w_wrong = root / "W"
    w_wrong.mkdir(parents=True)
    (w_wrong / "wrong.txt").write_text("wrong")

    link = root / "link"
    os.symlink(str(b_dir), str(link))

    wrapper_input = str(link) + "/../W/"

    action = {
        "type": "flatten_one_level",
        "wrapper_paths": [wrapper_input],
    }

    req = {
        "action": action,
        "expected_preview_digest": "a" * 64,
    }
    resp_gen = client.post("/api/batch-utilities/generate-plan", json=req)
    assert resp_gen.status_code == 409
    err = resp_gen.json()["error"]
    assert err["code"] == "BATCH_UTILITY_SYMLINK_BLOCKED"

    with service.SessionLocal() as session:
        plans = session.query(BatchPlan).all()
        assert len(plans) == 0


def test_generate_physically_distinct_wrappers_same_normpath_accepted(api_test_env):
    """E3-hotfix8 Regression B:
    Generate accepts physically distinct wrappers sharing textual normpath:
    p1: root/link/../W -> root/A/W
    p2: root/W -> root/W
    Expected: HTTP 201, draft plan generated with 2 items.
    """
    import os
    import json
    from app.models import BatchPlan
    client = api_test_env["client"]
    service = api_test_env["service"]
    root = api_test_env["root1_path"]

    a_dir = root / "A"
    b_dir = a_dir / "B"
    b_dir.mkdir(parents=True)
    w_a = a_dir / "W"
    w_a.mkdir(parents=True)
    (w_a / "a.txt").write_text("a")

    w_root = root / "W"
    w_root.mkdir(parents=True)
    (w_root / "root.txt").write_text("root")

    link = root / "link"
    os.symlink(str(b_dir), str(link))

    p1 = str(link) + "/../W"
    p2 = str(w_root)

    action = {
        "type": "flatten_one_level",
        "wrapper_paths": [p1, p2],
    }

    resp_prev = client.post("/api/batch-utilities/preview", json={"action": action})
    assert resp_prev.status_code == 200
    preview_digest = resp_prev.json()["preview_digest"]

    req = {
        "action": action,
        "expected_preview_digest": preview_digest,
    }
    resp_gen = client.post("/api/batch-utilities/generate-plan", json=req)
    assert resp_gen.status_code == 201

    with service.SessionLocal() as session:
        plans = session.query(BatchPlan).all()
        assert len(plans) == 1
        plan = plans[0]
        meta = json.loads(plan.metadata_json)
        canon_wrappers = set(meta["wrapper_paths"])
        assert str(w_a.resolve(strict=True)) in canon_wrappers
        assert str(w_root.resolve(strict=True)) in canon_wrappers
        assert len(plan.items) == 2


def test_generate_preflight_to_discovery_symlink_swap_blocks_enumeration(api_test_env):
    """E3-hotfix9 Generate regression:
    Stable preview acquired.
    During Generate, wrapper is swapped to symlink after preflight but before discovery.
    Assert:
    - Fails closed (HTTP 409 BATCH_UTILITY_SYMLINK_BLOCKED or PREVIEW_CHANGED).
    - 0 BatchPlan in DB.
    - 0 BatchPlanItem in DB.
    - No filesystem mutation, secret.txt is never enumerated into intents.
    """
    import os
    import shutil
    from unittest.mock import patch
    import app.batch_utilities.compiler as compiler_mod
    from app.models import BatchPlan

    client = api_test_env["client"]
    service = api_test_env["service"]
    root = api_test_env["root1_path"]

    a_dir = root / "A"
    b_dir = a_dir / "B"
    b_dir.mkdir(parents=True)
    real_dir = a_dir / "Real"
    real_dir.mkdir(parents=True)
    (real_dir / "secret.txt").write_text("secret")

    w_dir = a_dir / "W"
    w_dir.mkdir(parents=True)
    (w_dir / "before.txt").write_text("before")

    link = root / "link"
    os.symlink(str(b_dir), str(link))
    wrapper_input = str(link) + "/../W/"

    action = {
        "type": "flatten_one_level",
        "wrapper_paths": [wrapper_input],
    }

    resp_prev = client.post("/api/batch-utilities/preview", json={"action": action})
    assert resp_prev.status_code == 200
    preview_digest = resp_prev.json()["preview_digest"]

    # During Generate Phase A, swap wrapper after preflight
    orig_preflight = compiler_mod.validate_wrappers_preflight
    def racing_preflight(*args, **kwargs):
        res = orig_preflight(*args, **kwargs)
        shutil.rmtree(str(w_dir))
        os.symlink(str(real_dir), str(w_dir))
        return res

    discovered_in_generate = []
    orig_disc = compiler_mod.discover_flatten_one_level
    def spy_disc(wrappers, *args, **kwargs):
        cands, errs = orig_disc(wrappers, *args, **kwargs)
        discovered_in_generate.extend(cands)
        return cands, errs

    with patch("app.batch_utilities.compiler.validate_wrappers_preflight", side_effect=racing_preflight):
        with patch("app.batch_utilities.compiler.discover_flatten_one_level", side_effect=spy_disc):
            req = {
                "action": action,
                "expected_preview_digest": preview_digest,
            }
            resp_gen = client.post("/api/batch-utilities/generate-plan", json=req)
            assert resp_gen.status_code == 409
            err = resp_gen.json()["error"]
            assert err["code"] == "BATCH_UTILITY_SYMLINK_BLOCKED"

            with service.SessionLocal() as session:
                plans = session.query(BatchPlan).all()
                assert len(plans) == 0

    assert len(discovered_in_generate) == 0
    assert not any("secret.txt" in c.source_path for c in discovered_in_generate)
    assert (real_dir / "secret.txt").exists()


def test_generate_preflight_identity_capture_failure_fails_closed(api_test_env):
    """Gate5-E / E3-hotfix11 Test 2:
    Generate Phase A: If identity authority cannot be established during preflight,
    fails closed: 0 BatchPlan, 0 BatchPlanItem, 0 filesystem mutation.
    """
    import os
    from unittest.mock import patch
    from app.models import BatchPlan, BatchPlanItem
    import app.batch_utilities.compiler as compiler_mod

    client = api_test_env["client"]
    service = api_test_env["service"]
    root = api_test_env["root1_path"]
    w = root / "w_gen_identity_fail"
    w.mkdir()
    (w / "before.txt").write_text("before")
    w_phys_str = str(w.resolve())

    action = {
        "type": "flatten_one_level",
        "wrapper_paths": [str(w)]
    }

    resp_prev = client.post("/api/batch-utilities/preview", json={"action": action})
    assert resp_prev.status_code == 200
    preview_digest = resp_prev.json()["preview_digest"]

    # In Generate Phase A, fail preflight identity capture and swap W with secret.txt
    real_stat = os.stat
    stat_failed = False

    def failing_stat(path, *args, **kwargs):
        nonlocal stat_failed
        if not stat_failed and str(path) == w_phys_str:
            stat_failed = True
            w_old = root / "w_old"
            os.rename(str(w), str(w_old))
            w.mkdir()
            (w / "secret.txt").write_text("secret")
            raise OSError("Transient I/O failure during identity capture")
        return real_stat(path, *args, **kwargs)

    discovered_in_generate = []
    orig_disc = compiler_mod.discover_flatten_one_level

    def spy_disc(wrappers, *args, **kwargs):
        cands, errs = orig_disc(wrappers, *args, **kwargs)
        discovered_in_generate.extend(cands)
        return cands, errs

    with patch("os.stat", side_effect=failing_stat):
        with patch("app.batch_utilities.compiler.discover_flatten_one_level", side_effect=spy_disc):
            req = {
                "action": action,
                "expected_preview_digest": preview_digest
            }
            resp = client.post("/api/batch-utilities/generate-plan", json=req)
            assert resp.status_code in (400, 409, 422)
            err = resp.json()["error"]
            assert err["code"] == "BATCH_UTILITY_INVALID_CONFIG"

    # Verify zero discovery of replacement children
    assert len(discovered_in_generate) == 0
    assert not any("secret.txt" in c.source_path for c in discovered_in_generate)

    # Verify zero plans and zero items created in DB
    with service.SessionLocal() as session:
        plans = session.query(BatchPlan).all()
        assert len(plans) == 0
        items = session.query(BatchPlanItem).all()
        assert len(items) == 0

    # Verify secret.txt was not mutated
    assert (w / "secret.txt").exists()
