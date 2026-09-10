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

def test_preview_flatten_one_level(api_test_env):
    client = api_test_env["client"]
    root = api_test_env["root1_path"]
    
    wrapper = root / "wrapper"
    wrapper.mkdir()
    (wrapper / "a.txt").write_text("a")
    
    action = {
        "type": "flatten_one_level",
        "wrapper_paths": [str(wrapper)]
    }
    
    resp = client.post(
        "/api/batch-utilities/preview",
        json={"action": action, "page": 1, "page_size": 50}
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["utility_action"] == "flatten_one_level"
    assert data["preview_source"] == "live-directory-readonly"
    assert data["planned_operations_count"] == 1
    
    items = data["items"]
    assert len(items) == 1
    assert items[0]["source_path"] == str(wrapper / "a.txt")
    assert items[0]["target_path"] == str(root / "a.txt")
    assert items[0]["decision"] == "MOVE"
    assert items[0]["wrapper_path"] == str(wrapper)
    assert items[0]["object_type"] == "file"
    assert items[0]["index_root_id"] is None
    assert items[0]["index_root_path"] is None


def test_preview_wrapper_symlink_error(api_test_env):
    import os
    client = api_test_env["client"]
    root = api_test_env["root1_path"]
    
    real_wrapper = root / "real_w"
    real_wrapper.mkdir()
    sym_wrapper = root / "sym_w"
    os.symlink(str(real_wrapper), str(sym_wrapper))
    
    resp = client.post(
        "/api/batch-utilities/preview",
        json={"action": {"type": "flatten_one_level", "wrapper_paths": [str(sym_wrapper)]}}
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "BATCH_UTILITY_SYMLINK_BLOCKED"


def test_preview_wrapper_cross_root_error(api_test_env, tmp_path):
    client = api_test_env["client"]
    outside = tmp_path / "outside_w"
    outside.mkdir(parents=True)
    
    resp = client.post(
        "/api/batch-utilities/preview",
        json={"action": {"type": "flatten_one_level", "wrapper_paths": [str(outside)]}}
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "BATCH_UTILITY_CROSS_ROOT"


def test_preview_wrapper_child_symlink(api_test_env):
    import os
    client = api_test_env["client"]
    root = api_test_env["root1_path"]
    
    wrapper = root / "wrapper_sym_child"
    wrapper.mkdir()
    (wrapper / "real.txt").write_text("real")
    os.symlink("real.txt", wrapper / "link.txt")
    
    resp = client.post(
        "/api/batch-utilities/preview",
        json={"action": {"type": "flatten_one_level", "wrapper_paths": [str(wrapper)]}}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["planned_operations_count"] == 1
    rows_by_src = {it["source_path"]: it for it in data["items"]}
    assert rows_by_src[str(wrapper / "real.txt")]["decision"] == "MOVE"
    assert rows_by_src[str(wrapper / "link.txt")]["decision"] == "BLOCKING_CONFLICT"
    assert rows_by_src[str(wrapper / "link.txt")]["reason_code"] == "WRAPPER_CHILD_SYMLINK"


def test_preview_wrapper_scandir_failure_invalid_config(api_test_env):
    import os
    from unittest.mock import patch
    client = api_test_env["client"]
    root = api_test_env["root1_path"]
    wrapper = root / "unreadable_w"
    wrapper.mkdir()
    
    orig_scandir = os.scandir
    def mock_scandir(path):
        if str(path) == str(wrapper):
            err = PermissionError(13, "Permission denied")
            err.errno = 13
            raise err
        return orig_scandir(path)
        
    with patch("os.scandir", side_effect=mock_scandir):
        resp = client.post(
            "/api/batch-utilities/preview",
            json={"action": {"type": "flatten_one_level", "wrapper_paths": [str(wrapper)]}}
        )
        assert resp.status_code == 422
        err = resp.json()["error"]
        assert err["code"] == "BATCH_UTILITY_INVALID_CONFIG"
        assert err["details"].get("wrapper_path") == str(wrapper)
        assert err["details"].get("errno") == 13


def test_preview_quarantine_wrapper_error_cross_root(api_test_env):
    client = api_test_env["client"]
    settings = api_test_env["settings"]
    q_dir = settings.quarantine_root
    w_inside_q = q_dir / "q_wrapper"
    w_inside_q.mkdir()
    
    resp = client.post(
        "/api/batch-utilities/preview",
        json={"action": {"type": "flatten_one_level", "wrapper_paths": [str(w_inside_q)]}}
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "BATCH_UTILITY_CROSS_ROOT"


def test_preview_snapshot_second_scandir_failure_empty_wrapper(api_test_env):
    """E3-hotfix6 Regression:
    Empty wrapper scandir failure during snapshot capture.
    scan #1 (discovery): succeeds
    scan #2 (snapshot): PermissionError(errno=13)
    Expected: HTTP 422, BATCH_UTILITY_INVALID_CONFIG, stage=SNAPSHOT, errno=13
    """
    import os
    from unittest.mock import patch
    client = api_test_env["client"]
    root = api_test_env["root1_path"]
    wrapper = root / "w_empty_snap_err"
    wrapper.mkdir()

    orig_scandir = os.scandir
    call_count = 0

    def mock_scandir(path, *args, **kwargs):
        nonlocal call_count
        if os.path.normpath(str(path)) == str(wrapper):
            call_count += 1
            if call_count == 2:
                err = PermissionError(13, "Permission denied")
                err.errno = 13
                raise err
        return orig_scandir(path, *args, **kwargs)

    with patch("os.scandir", side_effect=mock_scandir):
        resp = client.post(
            "/api/batch-utilities/preview",
            json={"action": {"type": "flatten_one_level", "wrapper_paths": [str(wrapper)]}},
        )
        assert resp.status_code == 422
        err = resp.json()["error"]
        assert err["code"] == "BATCH_UTILITY_INVALID_CONFIG"
        assert err["details"].get("wrapper_path") == str(wrapper)
        assert err["details"].get("errno") == 13
        assert err["details"].get("stage") == "SNAPSHOT"


def test_preview_snapshot_second_scandir_failure_nonempty_wrapper(api_test_env):
    """E3-hotfix6 Regression:
    Nonempty wrapper scandir failure during snapshot capture.
    scan #1 (discovery): succeeds
    scan #2 (snapshot): PermissionError(errno=13)
    Expected: HTTP 422, BATCH_UTILITY_INVALID_CONFIG, stage=SNAPSHOT, errno=13
    """
    import os
    from unittest.mock import patch
    client = api_test_env["client"]
    root = api_test_env["root1_path"]
    wrapper = root / "w_nonempty_snap_err"
    wrapper.mkdir()
    (wrapper / "item.txt").write_text("hello")

    orig_scandir = os.scandir
    call_count = 0

    def mock_scandir(path, *args, **kwargs):
        nonlocal call_count
        if os.path.normpath(str(path)) == str(wrapper):
            call_count += 1
            if call_count == 2:
                err = PermissionError(13, "Permission denied")
                err.errno = 13
                raise err
        return orig_scandir(path, *args, **kwargs)

    with patch("os.scandir", side_effect=mock_scandir):
        resp = client.post(
            "/api/batch-utilities/preview",
            json={"action": {"type": "flatten_one_level", "wrapper_paths": [str(wrapper)]}},
        )
        assert resp.status_code == 422
        err = resp.json()["error"]
        assert err["code"] == "BATCH_UTILITY_INVALID_CONFIG"
        assert err["details"].get("wrapper_path") == str(wrapper)
        assert err["details"].get("errno") == 13
        assert err["details"].get("stage") == "SNAPSHOT"


def test_preview_canonical_wrapper_trailing_slash_digest_equality(api_test_env):
    """E3-hotfix6 Regression:
    W vs W/ selects the same wrapper and produces identical action_config_digest and preview_digest.
    """
    client = api_test_env["client"]
    root = api_test_env["root1_path"]
    wrapper = root / "w_slash_test"
    wrapper.mkdir()
    (wrapper / "item.txt").write_text("test")

    resp1 = client.post(
        "/api/batch-utilities/preview",
        json={"action": {"type": "flatten_one_level", "wrapper_paths": [str(wrapper)]}},
    )
    resp2 = client.post(
        "/api/batch-utilities/preview",
        json={"action": {"type": "flatten_one_level", "wrapper_paths": [str(wrapper) + "/"]}},
    )

    assert resp1.status_code == 200
    assert resp2.status_code == 200

    d1 = resp1.json()
    d2 = resp2.json()

    assert d1["action_config_digest"] == d2["action_config_digest"]
    assert d1["source_snapshot_digest"] == d2["source_snapshot_digest"]
    assert d1["preview_digest"] == d2["preview_digest"]
    assert d1["candidate_count"] == d2["candidate_count"] == 1


def test_preview_canonical_wrapper_ordering_digest_invariance(api_test_env):
    """E3-hotfix6 Regression:
    Wrapper input ordering is invariant for action_config_digest and preview_digest.
    """
    client = api_test_env["client"]
    root = api_test_env["root1_path"]
    w1 = root / "w_ord_1"
    w2 = root / "w_ord_2"
    w1.mkdir()
    w2.mkdir()
    (w1 / "f1.txt").write_text("1")
    (w2 / "f2.txt").write_text("2")

    resp1 = client.post(
        "/api/batch-utilities/preview",
        json={"action": {"type": "flatten_one_level", "wrapper_paths": [str(w1), str(w2)]}},
    )
    resp2 = client.post(
        "/api/batch-utilities/preview",
        json={"action": {"type": "flatten_one_level", "wrapper_paths": [str(w2), str(w1)]}},
    )

    assert resp1.status_code == 200
    assert resp2.status_code == 200

    d1 = resp1.json()
    d2 = resp2.json()

    assert d1["action_config_digest"] == d2["action_config_digest"]
    assert d1["source_snapshot_digest"] == d2["source_snapshot_digest"]
    assert d1["preview_digest"] == d2["preview_digest"]


def test_preview_canonical_wrapper_symlink_dotdot_selection(api_test_env):
    """E3-hotfix7 Regression:
    Preview selects actual physical directory via symlink-sensitive dotdot traversal.
    """
    import os
    client = api_test_env["client"]
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

    resp = client.post(
        "/api/batch-utilities/preview",
        json={"action": {"type": "flatten_one_level", "wrapper_paths": [wrapper_input]}},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["candidate_count"] == 1
    assert len(data["items"]) == 1
    item = data["items"][0]
    assert item["source_path"] == str(w_intended.resolve(strict=True) / "intended.txt")
    assert item["wrapper_path"] == str(w_intended.resolve(strict=True))
    assert item["target_path"] == str(a_dir.resolve(strict=True) / "intended.txt")


def test_preview_canonical_wrapper_trailing_space_directory(api_test_env):
    """E3-hotfix7 Regression:
    Preview preserves valid trailing space directory without stripping.
    """
    client = api_test_env["client"]
    root = api_test_env["root1_path"]

    w_wrong = root / "W"
    w_wrong.mkdir(parents=True)
    (w_wrong / "wrong.txt").write_text("wrong")

    w_space = root / "W "
    w_space.mkdir(parents=True)
    (w_space / "intended.txt").write_text("intended")

    wrapper_input = str(w_space)
    assert wrapper_input.endswith("W ")

    resp = client.post(
        "/api/batch-utilities/preview",
        json={"action": {"type": "flatten_one_level", "wrapper_paths": [wrapper_input]}},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["candidate_count"] == 1
    assert len(data["items"]) == 1
    item = data["items"][0]
    assert item["source_path"] == str(w_space.resolve(strict=True) / "intended.txt")
    assert item["wrapper_path"] == str(w_space.resolve(strict=True))
    assert item["wrapper_path"].endswith("W ")


def test_preview_symlink_sensitive_trailing_slash_leaf_symlink_blocked(api_test_env):
    """E3-hotfix8 API Regression A:
    Preview with trailing slash on symlink leaf: root/link/../W/
    must fail preflight with HTTP 409 BATCH_UTILITY_SYMLINK_BLOCKED.
    """
    import os
    client = api_test_env["client"]
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

    resp = client.post(
        "/api/batch-utilities/preview",
        json={"action": {"type": "flatten_one_level", "wrapper_paths": [wrapper_input]}},
    )
    assert resp.status_code == 409
    err = resp.json()["error"]
    assert err["code"] == "BATCH_UTILITY_SYMLINK_BLOCKED"


def test_preview_physically_distinct_wrappers_same_normpath_accepted(api_test_env):
    """E3-hotfix8 API Regression B:
    Preview accepts physically distinct wrappers even if normpath text is identical:
    p1: root/link/../W -> root/A/W
    p2: root/W -> root/W
    """
    import os
    client = api_test_env["client"]
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

    resp = client.post(
        "/api/batch-utilities/preview",
        json={"action": {"type": "flatten_one_level", "wrapper_paths": [p1, p2]}},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["candidate_count"] == 2
    sources = {item["source_path"] for item in data["items"]}
    assert str(w_a.resolve(strict=True) / "a.txt") in sources
    assert str(w_root.resolve(strict=True) / "root.txt") in sources


def test_preview_allowed_root_equality_symlink_dotdot_accepted(api_test_env):
    """E3-hotfix8 API Regression C:
    Preview accepts wrapper root/link/.. which resolves to root/A (not root).
    """
    import os
    client = api_test_env["client"]
    root = api_test_env["root1_path"]

    a_dir = root / "A"
    b_dir = a_dir / "B"
    b_dir.mkdir(parents=True)
    (a_dir / "item.txt").write_text("item")

    link = root / "link"
    os.symlink(str(b_dir), str(link))

    wrapper_input = str(link) + "/.."

    resp = client.post(
        "/api/batch-utilities/preview",
        json={"action": {"type": "flatten_one_level", "wrapper_paths": [wrapper_input]}},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["candidate_count"] == 2
    sources = {item["source_path"] for item in data["items"]}
    assert str(a_dir.resolve(strict=True) / "item.txt") in sources


def test_preview_preflight_to_discovery_symlink_swap_blocks_enumeration(api_test_env):
    """E3-hotfix9 API Preview regression:
    Wrapper swapped to symlink between preflight and discovery during preview.
    Preview must fail closed (HTTP 409 BATCH_UTILITY_SYMLINK_BLOCKED).
    secret.txt is never enumerated or returned in response.
    """
    import os
    import shutil
    from unittest.mock import patch
    import app.batch_utilities.compiler as compiler_mod

    client = api_test_env["client"]
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

    orig_preflight = compiler_mod.validate_wrappers_preflight
    def racing_preflight(*args, **kwargs):
        res = orig_preflight(*args, **kwargs)
        shutil.rmtree(str(w_dir))
        os.symlink(str(real_dir), str(w_dir))
        return res

    with patch("app.batch_utilities.compiler.validate_wrappers_preflight", side_effect=racing_preflight):
        resp = client.post(
            "/api/batch-utilities/preview",
            json={"action": {"type": "flatten_one_level", "wrapper_paths": [wrapper_input]}},
        )
        assert resp.status_code == 409
        err = resp.json()["error"]
        assert err["code"] == "BATCH_UTILITY_SYMLINK_BLOCKED"
        assert "secret.txt" not in resp.text


