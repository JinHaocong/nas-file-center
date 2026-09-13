from pathlib import Path

from app.batch.plans import OperationItem
from app.execution.executor import execute_item


def test_quarantine_purge_executor_rejects_missing_worker_authority(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    quarantine_root = data / ".nas-file-center-trash"
    quarantine_root.mkdir()
    source = quarantine_root / "entry.q-1.bin"
    source.write_bytes(b"gate6a-purge-executor")

    result = execute_item(
        OperationItem(sequence=1, operation="quarantine_purge", source=source),
        allowed_roots=[data],
        allow_mutation=True,
        allow_delete=True,
        quarantine_root=quarantine_root,
        plan_id="gate6a-purge",
    )

    assert result.state == "failed"
    assert "worker authority" in result.reason.lower()
    assert source.exists()
