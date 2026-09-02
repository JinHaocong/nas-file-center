from sqlalchemy import text


def test_sqlite_uses_wal_and_models_create(tmp_path):
    from app.db import create_engine_and_session, init_db
    from app.models import ScanJob

    db_path = tmp_path / "app.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine)

    with engine.connect() as conn:
        mode = conn.execute(text("PRAGMA journal_mode")).scalar_one().lower()
    assert mode == "wal"

    with SessionLocal() as session:
        session.add(ScanJob(name="test", mode="normal", roots_json='["/data"]', status="queued", fclones_args_json="{}"))
        session.commit()
        assert session.query(ScanJob).count() == 1
