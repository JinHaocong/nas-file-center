from sqlalchemy import inspect


def test_settings_default_quarantine_and_mutation_guard(monkeypatch):
    monkeypatch.delenv("QUARANTINE_ROOT", raising=False)
    monkeypatch.delenv("ALLOW_MUTATION", raising=False)
    from app.config import Settings

    settings = Settings(_env_file=None)
    assert str(settings.quarantine_root) == "/data/.nas-file-center-trash"
    assert settings.allow_mutation is False


def test_extended_models_create_and_persist(tmp_path):
    from app.db import create_engine_and_session, init_db
    from app.models import BatchPlan, BatchPlanItem, IndexedPath, WorkJob

    engine, SessionLocal = create_engine_and_session(tmp_path / "app.db")
    init_db(engine)
    names = set(inspect(engine).get_table_names())
    assert {"indexed_paths", "batch_plans", "batch_plan_items", "work_jobs"} <= names

    with SessionLocal() as session:
        entry = IndexedPath(
            root_key="root-a",
            absolute_path="/data/A/file.txt",
            relative_path="file.txt",
            basename="file.txt",
            stem="file",
            suffix=".txt",
            size=3,
            mtime_ns=1,
            device=2,
            inode=3,
            is_dir=False,
            scan_generation="g1",
        )
        plan = BatchPlan(name="rename", kind="rename", status="draft", metadata_json="{}")
        job = WorkJob(kind="index", status="queued", progress_current=0, progress_total=10, state_json="{}")
        session.add_all([entry, plan, job])
        session.flush()
        session.add(BatchPlanItem(
            plan_id=plan.id,
            sequence=1,
            operation="rename",
            source_path=entry.absolute_path,
            target_path="/data/A/file-2.txt",
            state="planned",
            metadata_json="{}",
        ))
        session.commit()

        assert session.query(IndexedPath).count() == 1
        assert session.query(BatchPlanItem).count() == 1
        assert session.query(WorkJob).one().progress_total == 10
