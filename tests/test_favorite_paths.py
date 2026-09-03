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
        user1 = User(
            username="admin",
            password_hash=hash_password("admin_password_123"),
            role="admin",
            is_active=True,
        )
        user2 = User(
            username="user2",
            password_hash=hash_password("user2_password_123"),
            role="admin",
            is_active=True,
        )
        session.add_all([user1, user2])
        session.commit()

    app = create_app(settings)
    return app, data_dir


def test_favorite_paths_crud_and_validation(tmp_path: Path):
    app, data_dir = _create_test_app(tmp_path)
    target_dir1 = data_dir / "Download" / "少女映画"
    target_dir1.mkdir(parents=True)
    target_dir2 = data_dir / "Photos"
    target_dir2.mkdir()

    client = TestClient(app)
    client.headers.update({"Origin": "http://testserver"})
    # Login as admin
    client.post("/api/auth/login", json={"username": "admin", "password": "admin_password_123"})

    # 1. Initially empty
    resp = client.get("/api/filesystem/favorites")
    assert resp.status_code == 200
    assert resp.json()["items"] == []

    # 2. Add valid favorite
    add_resp = client.post(
        "/api/filesystem/favorites",
        json={"path": str(target_dir1), "label": "少女映画专用"},
    )
    assert add_resp.status_code == 200
    fav1 = add_resp.json()
    assert fav1["path"] == str(target_dir1.resolve())
    assert fav1["label"] == "少女映画专用"
    assert fav1["exists"] is True

    # 3. Add second favorite
    client.post(
        "/api/filesystem/favorites",
        json={"path": str(target_dir2), "label": "相册目录"},
    )

    # 4. List favorites
    list_resp = client.get("/api/filesystem/favorites")
    assert list_resp.status_code == 200
    items = list_resp.json()["items"]
    assert len(items) == 2
    assert items[0]["label"] == "少女映画专用"
    assert items[1]["label"] == "相册目录"

    # 5. Add favorite outside ALLOWED_ROOTS -> 400
    bad_resp = client.post("/api/filesystem/favorites", json={"path": "/etc"})
    assert bad_resp.status_code in {400, 422}

    # 6. Add non-existent path -> 404
    non_existent = data_dir / "NotFoundDir"
    notfound_resp = client.post("/api/filesystem/favorites", json={"path": str(non_existent)})
    assert notfound_resp.status_code == 404

    # 7. Delete favorite
    del_resp = client.delete(f"/api/filesystem/favorites/{fav1['id']}")
    assert del_resp.status_code == 200

    # Verify deleted
    after_del = client.get("/api/filesystem/favorites").json()["items"]
    assert len(after_del) == 1
    assert after_del[0]["label"] == "相册目录"


def test_favorite_paths_user_isolation(tmp_path: Path):
    app, data_dir = _create_test_app(tmp_path)
    fav_dir = data_dir / "UserDir"
    fav_dir.mkdir()

    # User 1 creates favorite
    client1 = TestClient(app)
    client1.headers.update({"Origin": "http://testserver"})
    client1.post("/api/auth/login", json={"username": "admin", "password": "admin_password_123"})
    fav1 = client1.post("/api/filesystem/favorites", json={"path": str(fav_dir)}).json()

    # User 2 logs in
    client2 = TestClient(app)
    client2.headers.update({"Origin": "http://testserver"})
    client2.post("/api/auth/login", json={"username": "user2", "password": "user2_password_123"})

    # User 2 cannot see User 1's favorites
    items_u2 = client2.get("/api/filesystem/favorites").json()["items"]
    assert len(items_u2) == 0

    # User 2 cannot delete User 1's favorite
    del_res = client2.delete(f"/api/filesystem/favorites/{fav1['id']}")
    assert del_res.status_code == 404
