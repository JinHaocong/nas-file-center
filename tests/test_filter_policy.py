import pytest
from pathlib import Path
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session
from app.models import Base, FilterPolicy, IndexedPath, User
from app.auth.password import hash_password
from app.config import Settings
from app.filters.excludes import (
    validate_exclude_rules,
    build_exclude_predicates,
    DEFAULT_EXCLUDE_DIR_NAMES,
)
from app.db import init_db
from fastapi.testclient import TestClient
from app.main import create_app
from app.service import FileCenterService

def test_exclude_rule_validation():
    # Valid default rules
    rules = validate_exclude_rules([".git", ".recycle", "@eaDir"])
    assert rules == [".git", ".recycle", "@eaDir"]

    # Deduplication
    assert validate_exclude_rules([".git", ".git", "foo"]) == [".git", "foo"]

    # Max 64 rules
    with pytest.raises(ValueError, match="Maximum allowed exclude rules is 64"):
        validate_exclude_rules([f"dir_{i}" for i in range(65)])

    # Forbidden / or \
    with pytest.raises(ValueError, match="cannot contain path separators"):
        validate_exclude_rules(["foo/bar"])

    with pytest.raises(ValueError, match="cannot contain path separators"):
        validate_exclude_rules(["foo\\bar"])

    # Forbidden ., .., empty
    with pytest.raises(ValueError, match="cannot be empty or dot references"):
        validate_exclude_rules(["."])

    with pytest.raises(ValueError, match="cannot be empty or dot references"):
        validate_exclude_rules([".."])

    with pytest.raises(ValueError, match="cannot be empty or dot references"):
        validate_exclude_rules([""])

    # Whitespace in rule must be rejected without silent trimming
    with pytest.raises(ValueError, match="cannot contain leading or trailing whitespace"):
        validate_exclude_rules([" .git "])

def test_segment_aware_sql_excludes():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        paths = [
            IndexedPath(root_key="/data", absolute_path="/data/.git/config", relative_path=".git/config", basename="config", stem="config", suffix="", is_dir=False, scan_generation="g1"),
            IndexedPath(root_key="/data", absolute_path="/data/foo/.git/HEAD", relative_path="foo/.git/HEAD", basename="HEAD", stem="HEAD", suffix="", is_dir=False, scan_generation="g1"),
            IndexedPath(root_key="/data", absolute_path="/data/foo/.git2/file", relative_path="foo/.git2/file", basename="file", stem="file", suffix="", is_dir=False, scan_generation="g1"),
            IndexedPath(root_key="/data", absolute_path="/data/foo/my.git/file", relative_path="foo/my.git/file", basename="file", stem="file", suffix="", is_dir=False, scan_generation="g1"),
            IndexedPath(root_key="/data", absolute_path="/data/normal/file.txt", relative_path="normal/file.txt", basename="file.txt", stem="file", suffix=".txt", is_dir=False, scan_generation="g1"),
        ]
        session.add_all(paths)
        session.commit()

        # Build exclude predicate for [".git"]
        pred = build_exclude_predicates([".git"])
        stmt = select(IndexedPath.relative_path).where(pred)
        kept = set(session.scalars(stmt).all())
        assert kept == {"foo/.git2/file", "foo/my.git/file", "normal/file.txt"}

def test_filter_policy_api_rbac(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir(parents=True, exist_ok=True)
    config = tmp_path / "config"
    config.mkdir(parents=True, exist_ok=True)
    settings = Settings(
        config_dir=config,
        data_mount=data,
        allowed_roots_raw=str(data),
        initial_admin_username="admin",
        initial_admin_password="AdminPassword123!",
    )
    service = FileCenterService(settings)
    with service.SessionLocal() as session:
        reg_user = User(
            username="regular",
            password_hash=hash_password("UserPassword123!"),
            role="user",
        )
        session.add(reg_user)
        session.commit()

    app = create_app(settings)
    admin_client = TestClient(app)

    # Login admin
    login_admin = admin_client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "AdminPassword123!"},
        headers={"Origin": "http://testserver"},
    )
    assert login_admin.status_code == 200

    # Login regular user with a fresh client
    user_client = TestClient(app)
    login_user = user_client.post(
        "/api/auth/login",
        json={"username": "regular", "password": "UserPassword123!"},
        headers={"Origin": "http://testserver"},
    )
    assert login_user.status_code == 200

    # 1. Regular user GET -> 200
    res_get_user = user_client.get("/api/filter-policy")
    assert res_get_user.status_code == 200
    data_res = res_get_user.json()
    assert ".git" in data_res["exclude_dir_names"]

    # 2. Regular user PUT -> 403 Forbidden
    res_put_user = user_client.put(
        "/api/filter-policy",
        json={"exclude_dir_names": [".git", "custom_dir"]},
        headers={"Origin": "http://testserver"},
    )
    assert res_put_user.status_code == 403

    # Confirm policy unchanged in DB
    res_check = admin_client.get("/api/filter-policy")
    assert "custom_dir" not in res_check.json()["exclude_dir_names"]

    # 3. Admin PUT -> 200 OK
    res_put_admin = admin_client.put(
        "/api/filter-policy",
        json={"exclude_dir_names": [".git", ".recycle", "@eaDir", ".nas-file-center-trash", "my_secret_dir"]},
        headers={"Origin": "http://testserver"},
    )
    assert res_put_admin.status_code == 200
    assert "my_secret_dir" in res_put_admin.json()["exclude_dir_names"]

def test_migration_and_idempotency(tmp_path: Path):
    db_file = tmp_path / "migration_test.db"
    backups_dir = tmp_path / "backups"
    engine = create_engine(f"sqlite:///{db_file}")

    # First init creates tables and seeds filter_policy
    init_db(engine, db_path=db_file, backups_dir=backups_dir)
    with Session(engine) as session:
        policy = session.get(FilterPolicy, 1)
        assert policy is not None
        assert ".git" in policy.exclude_dir_names_json

        # Modify policy
        policy.exclude_dir_names_json = '["custom_rule"]'
        session.commit()

    # Second init must be idempotent and NOT overwrite user config
    init_db(engine, db_path=db_file, backups_dir=backups_dir)
    with Session(engine) as session:
        policy2 = session.get(FilterPolicy, 1)
        assert policy2 is not None
        assert policy2.exclude_dir_names_json == '["custom_rule"]'

        # Verify integrity and foreign key checks
        integrity = session.execute(text("PRAGMA integrity_check")).scalar()
        assert integrity == "ok"
        fk_check = session.execute(text("PRAGMA foreign_key_check")).all()
        assert fk_check == []
