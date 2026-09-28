from __future__ import annotations

from pathlib import Path
import sqlite3

from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest
from sqlalchemy import inspect

from app.config import Settings
from app.db import create_engine_and_session, init_db
from app.main import create_app
from app.workflows.schema import OrganizerProfileSnapshot


def _client(tmp_path: Path) -> TestClient:
    data = tmp_path / "data"
    data.mkdir()
    config = tmp_path / "config"
    config.mkdir()
    settings = Settings(
        config_dir=config,
        data_mount=data,
        allowed_roots_raw=str(data),
        allow_mutation=False,
        allow_delete=False,
        initial_admin_username="admin",
        initial_admin_password="AdminPassword123!",
    )
    client = TestClient(create_app(settings))
    client.headers.update({"Origin": "http://testserver"})
    login = client.post("/api/auth/login", json={"username": "admin", "password": "AdminPassword123!"})
    assert login.status_code == 200
    return client


def _advanced_rules() -> dict:
    return {
        "version": 1,
        "directory_depth": {"enabled": True, "rename_from_depth": 2},
        "file_numbering": {
            "enabled": True,
            "start": 1,
            "padding": 3,
            "sort": "natural_name",
            "extension_mode": "preserve",
        },
        "latest_child_prefix": {
            "enabled": False,
            "prefix": "New ",
            "timestamp": "mtime_ns",
        },
        "single_child_wrapper_collapse": {
            "enabled": False,
            "wrapper_depth": 2,
            "child_type": "directory",
        },
    }


def test_profile_advanced_rules_roundtrip_and_legacy_default(tmp_path: Path):
    client = _client(tmp_path)

    legacy = client.post("/api/organizer-profiles", json={"name": "legacy"})
    assert legacy.status_code == 200
    assert legacy.json()["advanced_rules"] == {}

    advanced = client.post(
        "/api/organizer-profiles",
        json={
            "name": "advanced",
            "recursive": True,
            "advanced_rules": _advanced_rules(),
        },
    )
    assert advanced.status_code == 200, advanced.text
    body = advanced.json()
    assert body["advanced_rules"]["version"] == 1
    assert body["advanced_rules"]["directory_depth"]["rename_from_depth"] == 2
    assert body["advanced_rules"]["file_numbering"]["enabled"] is True

    fetched = client.get(f"/api/organizer-profiles/{body['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["advanced_rules"] == body["advanced_rules"]


def test_advanced_rules_cross_field_validation_is_fail_closed(tmp_path: Path):
    client = _client(tmp_path)

    not_recursive = client.post(
        "/api/organizer-profiles",
        json={
            "name": "blocked",
            "recursive": False,
            "advanced_rules": _advanced_rules(),
        },
    )
    assert not_recursive.status_code == 400
    assert "recursive" in not_recursive.json()["detail"]

    latest = _advanced_rules()
    latest["directory_depth"]["enabled"] = False
    latest["file_numbering"]["enabled"] = False
    latest["latest_child_prefix"]["enabled"] = True
    ordered = client.post(
        "/api/organizer-profiles",
        json={
            "name": "ordered-blocked",
            "recursive": True,
            "mtime_mode": "ordered",
            "advanced_rules": latest,
        },
    )
    assert ordered.status_code == 400
    assert "ordered mtime" in ordered.json()["detail"]

    unknown = client.post(
        "/api/organizer-profiles",
        json={
            "name": "unknown",
            "recursive": True,
            "advanced_rules": {"version": 1, "unexpected": True},
        },
    )
    assert unknown.status_code == 422


def test_export_v2_and_import_v1_v2_are_compatible(tmp_path: Path):
    client = _client(tmp_path)

    created = client.post(
        "/api/organizer-profiles",
        json={"name": "v2", "recursive": True, "advanced_rules": _advanced_rules()},
    )
    assert created.status_code == 200
    profile_id = created.json()["id"]

    exported = client.get(f"/api/organizer-profiles/{profile_id}/export")
    assert exported.status_code == 200
    payload = exported.json()
    assert payload["schema_version"] == 2
    assert payload["profile"]["advanced_rules"]["version"] == 1

    imported_v2 = client.post("/api/organizer-profiles/import", json=payload)
    assert imported_v2.status_code == 200, imported_v2.text
    assert imported_v2.json()["advanced_rules"]["file_numbering"]["enabled"] is True

    imported_v1 = client.post(
        "/api/organizer-profiles/import",
        json={
            "schema_version": 1,
            "profile": {
                "name": "legacy-import",
                "recursive": False,
            },
        },
    )
    assert imported_v1.status_code == 200, imported_v1.text
    assert imported_v1.json()["advanced_rules"] == {}


def test_v2_import_rejects_string_recursive_coercion(tmp_path: Path):
    client = _client(tmp_path)
    payload = {
        "schema_version": 2,
        "profile": {
            "name": "strict-recursive",
            "recursive": "false",
            "advanced_rules": _advanced_rules(),
        },
    }
    response = client.post("/api/organizer-profiles/import", json=payload)
    assert response.status_code == 400
    assert "recursive" in response.json()["detail"]


def test_workflow_snapshot_accepts_legacy_and_validates_advanced_rules():
    legacy = OrganizerProfileSnapshot(name="legacy")
    assert legacy.advanced_rules is None

    advanced = OrganizerProfileSnapshot(
        name="advanced",
        recursive=True,
        advanced_rules=_advanced_rules(),
    )
    assert advanced.advanced_rules is not None
    assert advanced.advanced_rules.file_numbering.enabled is True

    with pytest.raises(ValidationError):
        OrganizerProfileSnapshot(
            name="blocked",
            recursive=False,
            advanced_rules=_advanced_rules(),
        )


def test_existing_organizer_table_is_additively_migrated_with_backup(tmp_path: Path):
    db_path = tmp_path / "config" / "app.db"
    backups_dir = tmp_path / "config" / "backups"
    db_path.parent.mkdir(parents=True)

    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE organizer_profiles (
            id INTEGER PRIMARY KEY,
            user_id INTEGER,
            slug VARCHAR(64),
            builtin_version INTEGER,
            name VARCHAR(255),
            description TEXT,
            root TEXT,
            recursive BOOLEAN DEFAULT 0,
            image_extensions TEXT DEFAULT '[]',
            video_extensions TEXT DEFAULT '[]',
            rename_template VARCHAR(500),
            statistics_template VARCHAR(500),
            preserve_tags TEXT DEFAULT '[]',
            cleanup_patterns TEXT DEFAULT '[]',
            numbering_mode VARCHAR(32) DEFAULT 'none',
            numbering_start INTEGER DEFAULT 1,
            numbering_padding INTEGER DEFAULT 3,
            mtime_mode VARCHAR(32) DEFAULT 'none',
            mtime_delay_seconds FLOAT DEFAULT 2.0,
            is_builtin BOOLEAN DEFAULT 0,
            created_at DATETIME,
            updated_at DATETIME
        )
        """
    )
    conn.commit()
    conn.close()

    engine, _SessionLocal = create_engine_and_session(db_path)
    init_db(engine, db_path=db_path, backups_dir=backups_dir)

    columns = {column["name"] for column in inspect(engine).get_columns("organizer_profiles")}
    assert "advanced_rules_json" in columns
    assert list(backups_dir.glob("nas-file-center-*.db"))
