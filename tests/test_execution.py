import hashlib
from pathlib import Path


def H(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_duplicate_quarantine_rehashes_and_preserves_keep(tmp_path):
    root = tmp_path / "data"; a_dir = root / "A"; b_dir = root / "B"
    a_dir.mkdir(parents=True); b_dir.mkdir()
    keep = a_dir / "x.bin"; delete = b_dir / "x.bin"
    payload = b"same-content" * 1000
    keep.write_bytes(payload); delete.write_bytes(payload)

    from app.batch.plans import OperationItem
    from app.execution.executor import execute_item
    item = OperationItem(
        sequence=1,
        operation="quarantine",
        source=delete,
        keep=keep,
        expected_size=len(payload),
        expected_hash=H(payload),
    )
    result = execute_item(
        item,
        allowed_roots=[root],
        allow_mutation=True,
        allow_delete=False,
        quarantine_root=root / ".trash",
        plan_id="p1",
    )
    assert result.state == "completed"
    assert keep.exists() and not delete.exists()
    assert result.result_path is not None and result.result_path.exists()
    assert result.result_path.read_bytes() == payload


def test_duplicate_quarantine_safe_skips_changed_hash(tmp_path):
    root = tmp_path / "data"; root.mkdir()
    keep = root / "a"; delete = root / "b"
    keep.write_bytes(b"same"); delete.write_bytes(b"changed")
    from app.batch.plans import OperationItem
    from app.execution.executor import execute_item
    item = OperationItem(1, "quarantine", delete, keep=keep, expected_size=4, expected_hash=H(b"same"))
    result = execute_item(item, allowed_roots=[root], allow_mutation=True, allow_delete=False, quarantine_root=root / ".trash", plan_id="p")
    assert result.state == "skipped"
    assert delete.exists()


def test_mutation_disabled_and_unlink_separately_guarded(tmp_path):
    root = tmp_path / "data"; root.mkdir(); f = root / "x"; f.write_text("x")
    from app.batch.plans import OperationItem
    from app.execution.executor import execute_item
    item = OperationItem(1, "unlink", f, expected_size=1)
    disabled = execute_item(item, allowed_roots=[root], allow_mutation=False, allow_delete=True, quarantine_root=root / ".trash", plan_id="p")
    assert disabled.state == "skipped" and f.exists()
    delete_disabled = execute_item(item, allowed_roots=[root], allow_mutation=True, allow_delete=False, quarantine_root=root / ".trash", plan_id="p")
    assert delete_disabled.state == "skipped" and f.exists()


def test_symlink_is_never_mutated(tmp_path):
    root = tmp_path / "data"; root.mkdir(); real = root / "real"; real.write_text("x")
    link = root / "link"; link.symlink_to(real)
    from app.batch.plans import OperationItem
    from app.execution.executor import execute_item
    item = OperationItem(1, "quarantine", link, expected_size=1)
    result = execute_item(item, allowed_roots=[root], allow_mutation=True, allow_delete=False, quarantine_root=root / ".trash", plan_id="p")
    assert result.state == "skipped" and link.is_symlink() and real.exists()


def test_rename_refuses_existing_target_and_completed_item_resumes_as_noop(tmp_path):
    root = tmp_path / "data"; root.mkdir(); src = root / "a"; target = root / "b"
    src.write_text("a"); target.write_text("b")
    from app.batch.plans import OperationItem
    from app.execution.executor import execute_item
    collision = OperationItem(1, "rename", src, target=target, expected_size=1)
    r1 = execute_item(collision, allowed_roots=[root], allow_mutation=True, allow_delete=False, quarantine_root=root / ".trash", plan_id="p")
    assert r1.state == "skipped" and src.exists() and target.read_text() == "b"

    already = OperationItem(2, "rename", src, target=root / "c", expected_size=1, state="completed")
    r2 = execute_item(already, allowed_roots=[root], allow_mutation=True, allow_delete=False, quarantine_root=root / ".trash", plan_id="p")
    assert r2.state == "completed" and r2.reason == "already completed" and src.exists()


def test_protected_directory_last_file_is_not_quarantined(tmp_path):
    root = tmp_path / "data"; protected = root / "set"; protected.mkdir(parents=True)
    src = protected / "only.jpg"; src.write_text("x")
    from app.batch.plans import OperationItem
    from app.execution.executor import execute_item
    item = OperationItem(1, "quarantine", src, expected_size=1, protected_dir=protected)
    result = execute_item(item, allowed_roots=[root], allow_mutation=True, allow_delete=False, quarantine_root=root / ".trash", plan_id="p")
    assert result.state == "skipped" and "last file" in result.reason and src.exists()
