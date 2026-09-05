import sqlite3
from pathlib import Path
from sqlalchemy import inspect, select, text

from app.db import create_engine_and_session, init_db
from app.models import (
    Base,
    BatchPlan,
    BatchPlanItem,
    OperationJournal,
    QuarantineEntry,
    User,
    WorkJob,
    utcnow,
)


def test_operation_journal_model_and_indexes(tmp_path: Path):
    db_path = tmp_path / "test.db"
    backups_dir = tmp_path / "backups"
    engine, session_factory = create_engine_and_session(db_path)
    init_db(engine, db_path=db_path, backups_dir=backups_dir)

    inspector = inspect(engine)
    assert "operation_journal" in inspector.get_table_names()

    columns = {col["name"]: col for col in inspector.get_columns("operation_journal")}
    expected_cols = [
        "id",
        "operation",
        "sequence",
        "plan_id",
        "plan_item_id",
        "task_id",
        "user_id",
        "before_json",
        "after_json",
        "metadata_before_json",
        "metadata_after_json",
        "created_at",
    ]
    for col in expected_cols:
        assert col in columns, f"Column '{col}' missing from operation_journal"

    # Foreign keys check
    fks = inspector.get_foreign_keys("operation_journal")
    fk_map = {fk["constrained_columns"][0]: (fk["referred_table"], fk["referred_columns"][0], fk.get("options", {}).get("ondelete")) for fk in fks}
    assert "plan_id" in fk_map
    assert fk_map["plan_id"][:2] == ("batch_plans", "id")
    assert fk_map["plan_id"][2] == "SET NULL"

    assert "plan_item_id" in fk_map
    assert fk_map["plan_item_id"][:2] == ("batch_plan_items", "id")
    assert fk_map["plan_item_id"][2] == "SET NULL"

    assert "task_id" in fk_map
    assert fk_map["task_id"][:2] == ("work_jobs", "id")
    assert fk_map["task_id"][2] == "SET NULL"

    assert "user_id" in fk_map
    assert fk_map["user_id"][:2] == ("users", "id")
    assert fk_map["user_id"][2] == "SET NULL"

    # Indexes check
    indexes = inspector.get_indexes("operation_journal")
    idx_cols = [tuple(idx["column_names"]) for idx in indexes]
    assert ("plan_id", "sequence") in idx_cols or any(set(c) == {"plan_id", "sequence"} for c in idx_cols)
    assert any("task_id" in c for c in idx_cols)
    assert any("plan_item_id" in c for c in idx_cols)
    assert any("created_at" in c for c in idx_cols)
    assert any("operation" in c for c in idx_cols)

    engine.dispose()


def test_operation_journal_append_only_and_set_null(tmp_path: Path):
    db_path = tmp_path / "test.db"
    backups_dir = tmp_path / "backups"
    engine, session_factory = create_engine_and_session(db_path)
    init_db(engine, db_path=db_path, backups_dir=backups_dir)

    with session_factory() as session:
        user = User(username="admin_test", password_hash="hash", role="admin")
        session.add(user)
        plan = BatchPlan(name="Test Plan", kind="organize", status="completed")
        session.add(plan)
        session.flush()

        item = BatchPlanItem(plan_id=plan.id, sequence=1, operation="rename", source_path="/data/a.txt", target_path="/data/b.txt", state="completed")
        job = WorkJob(kind="batch-plan-execute", status="completed")
        session.add_all([item, job])
        session.flush()

        journal = OperationJournal(
            operation="rename",
            sequence=1,
            plan_id=plan.id,
            plan_item_id=item.id,
            task_id=job.id,
            user_id=user.id,
            before_json='{"path": "/data/a.txt"}',
            after_json='{"path": "/data/b.txt"}',
            metadata_before_json='{"size": 100}',
            metadata_after_json='{"size": 100}',
            created_at=utcnow(),
        )
        session.add(journal)
        session.commit()
        journal_id = journal.id

    # Now delete the plan (or task) - journal must NOT be deleted, but set null
    with session_factory() as session:
        p = session.get(BatchPlan, plan.id)
        session.delete(p)
        session.commit()

    with session_factory() as session:
        j = session.get(OperationJournal, journal_id)
        assert j is not None, "OperationJournal must NOT be cascade deleted!"
        assert j.plan_id is None
        assert j.operation == "rename"

    engine.dispose()


def test_migration_from_gate1_creates_backup_and_journal(tmp_path: Path):
    db_path = tmp_path / "legacy.db"
    backups_dir = tmp_path / "backups"

    # Simulate Gate1-hotfix2 DB (has quarantine_entries, data_lifecycle_policy, etc., but no operation_journal)
    engine, _ = create_engine_and_session(db_path)
    # Create tables without operation_journal
    tables_to_create = [t for name, t in Base.metadata.tables.items() if name != "operation_journal"]
    Base.metadata.create_all(engine, tables=tables_to_create)
    engine.dispose()

    # Now run init_db
    engine2, _ = create_engine_and_session(db_path)
    init_db(engine2, db_path=db_path, backups_dir=backups_dir)

    # 1. Verify backup was made
    backups = list(backups_dir.glob("*.db"))
    assert len(backups) == 1, "Backup must be created before schema migration"

    # 2. Verify operation_journal exists
    insp = inspect(engine2)
    assert "operation_journal" in insp.get_table_names()

    # 3. Verify PRAGMA integrity_check and foreign_key_check
    with engine2.connect() as conn:
        res = conn.execute(text("PRAGMA integrity_check;")).fetchall()
        assert res == [("ok",)]
        fk_res = conn.execute(text("PRAGMA foreign_key_check;")).fetchall()
        assert len(fk_res) == 0

    # 4. Second run must NOT create redundant backup
    init_db(engine2, db_path=db_path, backups_dir=backups_dir)
    backups_after = list(backups_dir.glob("*.db"))
    assert len(backups_after) == 1, "Second startup must NOT create redundant backup"

    engine2.dispose()
