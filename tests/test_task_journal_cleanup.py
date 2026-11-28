from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.config import Settings
from app.maintenance.journal import preview_operation_journal_archive
from app.models import BatchPlan, OperationJournal as Journal, WorkJob
from app.service import FileCenterService


@pytest.fixture
def service(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    instance = FileCenterService(Settings(
        config_dir=tmp_path / "config", data_mount=data, allowed_roots_raw=str(data),
        quarantine_root=data / ".trash",
    ))
    yield instance
    instance.engine.dispose()


@pytest.mark.parametrize("bulk", [False, True])
def test_physical_task_delete_purges_owned_operations_and_preserves_watermark(service, bulk):
    with service.SessionLocal.begin() as session:
        session.add_all([WorkJob(id=1, kind="test", status="completed"),
                         WorkJob(id=2, kind="test", status="running")])
        session.flush()
        session.add_all([Journal(id=1, task_id=1, operation="move"),
                         Journal(id=2, task_id=1, operation="quarantine_unlink_purge"),
                         Journal(id=3, task_id=2, operation="touch"),
                         Journal(id=4, operation="rename"),
                         Journal(id=5, task_id=1, operation="rmdir_empty",
                                 after_json='{"quarantine_path":"/retained"}'),
                         Journal(id=6, task_id=1, operation="quarantine",
                                 after_json='{"quarantine_entry_id":42,"quarantine_path":"/q"}'),
                         Journal(id=7, task_id=1, operation="touch", sequence=777,
                                 before_json='{"path":"private"}')])
    if bulk:
        service.clear_task_history(["completed"])
    else:
        service.delete_task(1)
    assert [r["id"] for r in service.list_operation_journal()["items"]] == [6, 5, 4, 3, 2]
    with service.SessionLocal.begin() as session:
        session.add(WorkJob(id=3, kind="test", status="completed"))
        session.flush()
        row = Journal(task_id=3, operation="rename")
        session.add(row)
        session.flush()
        assert row.id == 8
    service.delete_task(3)
    with service.SessionLocal() as session:
        assert set(session.scalars(select(Journal.id))) == {2, 3, 4, 5, 6, 8}
        assert session.get(Journal, 8).before_json == "{}"


@pytest.mark.parametrize("bulk", [False, True])
def test_deferred_task_purge_waits_for_source_and_undo_plan(service, bulk):
    with service.SessionLocal.begin() as session:
        session.add_all([BatchPlan(id=1, name="Source", kind="batch", status="completed"),
                         WorkJob(id=1, kind="test", status="completed")])
        session.flush()
        session.add_all([Journal(id=1, task_id=1, plan_id=1, operation="move"),
                         Journal(id=2, plan_id=1, operation="rename")])
    service.delete_task(1)
    assert service.list_operation_journal(plan_id=1)["total"] == 2
    service.create_undo_plan(1)
    if bulk:
        service.clear_plan_history(["completed"])
    else:
        service.delete_plan(1)
    assert service.list_operation_journal()["total"] == 2
    # Source rows still used by the undo plan must survive periodic archival too.
    assert preview_operation_journal_archive(
        service.SessionLocal, datetime.now() + timedelta(days=1),
    ) == {"rows": 0}
    service.delete_plan(2)
    assert [r["id"] for r in service.list_operation_journal()["items"]] == [2]


def test_legacy_undo_item_reference_survives_without_plan_summary(service):
    with service.SessionLocal.begin() as session:
        session.add_all([BatchPlan(id=1, name="Source", kind="batch", status="completed"),
                         WorkJob(id=1, kind="test", status="completed")])
        session.flush()
        session.add(Journal(id=1, task_id=1, plan_id=1, operation="touch"))
    service.create_undo_plan(1)
    with service.SessionLocal.begin() as session:
        session.get(BatchPlan, 2).metadata_json = "{}"
    service.delete_plan(1)
    service.delete_task(1)
    assert service.list_operation_journal()["total"] == 1
    service.delete_plan(2)
    assert service.list_operation_journal()["total"] == 0
