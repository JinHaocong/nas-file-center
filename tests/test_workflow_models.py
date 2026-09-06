import pytest
import sqlite3
from pathlib import Path
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.exc import IntegrityError

from app.models import Base, Workflow, WorkflowRevision, User
from app.db import init_db, create_engine_and_session


def test_workflow_models_and_constraints(tmp_path: Path):
    db_file = tmp_path / "test.db"
    engine, SessionLocal = create_engine_and_session(db_file)
    init_db(engine, db_path=db_file)

    with SessionLocal() as session:
        # Create user
        user = User(username="admin_user", password_hash="hash", role="admin")
        session.add(user)
        session.commit()
        user_id = user.id

        # Create workflow
        wf = Workflow(
            name="Test Workflow",
            description="Test description",
            current_revision=1,
            is_builtin=False,
            created_by_user_id=user_id,
        )
        session.add(wf)
        session.commit()
        wf_id = wf.id

        # Create revision 1
        rev1 = WorkflowRevision(
            workflow_id=wf_id,
            revision=1,
            definition_json='{"schema_version": 1, "mode": "file", "steps": []}',
            definition_sha256="abc123sha",
            created_by_user_id=user_id,
        )
        session.add(rev1)
        session.commit()

        # Query workflow with revisions
        fetched_wf = session.get(Workflow, wf_id)
        assert fetched_wf is not None
        assert fetched_wf.name == "Test Workflow"
        assert fetched_wf.current_revision == 1
        assert fetched_wf.archived_at is None
        assert len(fetched_wf.revisions) == 1
        assert fetched_wf.revisions[0].revision == 1
        assert fetched_wf.revisions[0].definition_sha256 == "abc123sha"

        # Create revision 2
        rev2 = WorkflowRevision(
            workflow_id=wf_id,
            revision=2,
            definition_json='{"schema_version": 1, "mode": "file", "steps": [{"id": "s1"}]}',
            definition_sha256="def456sha",
            created_by_user_id=user_id,
        )
        session.add(rev2)
        fetched_wf.current_revision = 2
        session.commit()
        session.refresh(fetched_wf)

        assert len(fetched_wf.revisions) == 2

    # Test UNIQUE(workflow_id, revision) constraint
    with SessionLocal() as session:
        dup_rev = WorkflowRevision(
            workflow_id=wf_id,
            revision=2,
            definition_json='{"schema_version": 1}',
            definition_sha256="dup",
            created_by_user_id=user_id,
        )
        session.add(dup_rev)
        with pytest.raises(IntegrityError):
            session.commit()


def test_workflow_migration_on_existing_db(tmp_path: Path):
    db_file = tmp_path / "legacy.db"
    backups_dir = tmp_path / "backups"

    # 1. Create a legacy database without workflows/workflow_revisions using Base.metadata
    legacy_engine = create_engine(f"sqlite:///{db_file}")
    legacy_tables = [t for t in Base.metadata.sorted_tables if t.name not in ("workflows", "workflow_revisions")]
    Base.metadata.create_all(legacy_engine, tables=legacy_tables)

    # Insert a legacy user
    with Session(legacy_engine) as session:
        user = User(username="legacy_admin", password_hash="hash", role="admin")
        session.add(user)
        session.commit()
    legacy_engine.dispose()

    # 2. Run init_db -> should trigger backup and add workflows tables
    engine, SessionLocal = create_engine_and_session(db_file)
    init_db(engine, db_path=db_file, backups_dir=backups_dir)

    # Verify backup exists
    backups = list(backups_dir.glob("*.db"))
    assert len(backups) >= 1

    # Verify legacy data preserved
    with SessionLocal() as session:
        user = session.get(User, 1)
        assert user is not None
        assert user.username == "legacy_admin"

        # Verify new tables exist and writable
        wf = Workflow(name="New WF", current_revision=1)
        session.add(wf)
        session.commit()
        assert wf.id is not None
