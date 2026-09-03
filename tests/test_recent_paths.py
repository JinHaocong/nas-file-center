from __future__ import annotations

from pathlib import Path
from fastapi.testclient import TestClient

from app.auth.password import hash_password
from app.config import Settings
from app.db import create_engine_and_session, init_db
from app.main import create_app
from app.models import User


def _create_test_app(tmp_path: Path):
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    db_path = config_dir / "app.db"
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

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
        allowed_roots_raw=str(data_dir),
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
    return app, data_dir


def test_recent_paths_record_and_limit(tmp_path: Path):
    app, data_dir = _create_test_app(tmp_path)
    dirs = []
    for i in range(25):
        d = data_dir / f"Folder_{i:02d}"
        d.mkdir()
        dirs.append(str(d))

    client = TestClient(app)
    client.headers.update({"Origin": "http://testserver"})
    client.post("/api/auth/login", json={"username": "admin", "password": "admin_password_123"})

    # 1. Record 25 paths in batches
    client.post("/api/filesystem/recent", json={"paths": dirs[:10]})
    resp1 = client.get("/api/filesystem/recent")
    assert resp1.status_code == 200
    assert len(resp1.json()["items"]) == 10

    # Record more to test 20 cap
    client.post("/api/filesystem/recent", json={"paths": dirs[10:25]})
    resp2 = client.get("/api/filesystem/recent")
    assert resp2.status_code == 200
    items = resp2.json()["items"]
    # Maximum 20 paths retained
    assert len(items) == 20

    # 2. Record duplicate path: updates last_used_at rather than inserting duplicate
    first_path = items[0]["path"]
    client.post("/api/filesystem/recent", json={"paths": [first_path]})
    resp3 = client.get("/api/filesystem/recent")
    items3 = resp3.json()["items"]
    assert len(items3) == 20
    # The duplicate should now be at top
    assert items3[0]["path"] == first_path
