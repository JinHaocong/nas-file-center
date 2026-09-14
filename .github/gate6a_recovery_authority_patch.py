from pathlib import Path
import ast

handlers_path = Path("app/tasks/handlers.py")
handlers = handlers_path.read_text()

old_decl = '        gate6a_authority_loss: dict[int, tuple[int | None, str]] = {}\n'
new_decl = '        gate6a_authority_loss: dict[int, tuple[int | None, str | None, str | None, str]] = {}\n'
assert handlers.count(old_decl) == 1, handlers.count(old_decl)
handlers = handlers.replace(old_decl, new_decl, 1)

restore_anchor = '                elif it.operation == "restore":\n'
restore_pos = handlers.index(restore_anchor, handlers.index("class BatchPlanExecuteHandler"))
block_start = handlers.index('                    if is_gate6a_restore_recovery:\n', restore_pos)
block_end_marker = '''                    else:
                        meta = json.loads(it.metadata_json or "{}")
                        qid = meta.get("quarantine_entry_id") or meta.get("undo", {}).get("quarantine_entry_id")
                        qe = session.get(QuarantineEntry, int(qid)) if qid else None
'''
block_end = handlers.index(block_end_marker, block_start)

new_recovery_block = '''                    if is_gate6a_restore_recovery:
                        from app.quarantine.bulk_lifecycle import _gate6a_restore_binding_error

                        try:
                            recovery_plan_meta = json.loads(recovery_plan.metadata_json or "{}")
                        except Exception:
                            recovery_plan_meta = {}
                        if not isinstance(recovery_plan_meta, dict):
                            recovery_plan_meta = {}
                        authority_map = recovery_plan_meta.get("restore_item_authority")
                        authority = authority_map.get(str(it.id)) if isinstance(authority_map, dict) else None

                        frozen_qid = None
                        frozen_source = None
                        frozen_target = None
                        binding_error = None
                        if not isinstance(authority, dict):
                            binding_error = "missing frozen restore_item_authority"
                        else:
                            raw_frozen_qid = authority.get("quarantine_entry_id")
                            if not isinstance(raw_frozen_qid, int) or isinstance(raw_frozen_qid, bool) or raw_frozen_qid <= 0:
                                binding_error = "invalid frozen quarantine_entry_id authority"
                            else:
                                frozen_qid = int(raw_frozen_qid)
                            frozen_source = authority.get("source_path") if isinstance(authority.get("source_path"), str) else None
                            frozen_target = authority.get("target_path") if isinstance(authority.get("target_path"), str) else None

                        frozen_qe = session.get(QuarantineEntry, frozen_qid) if frozen_qid is not None else None
                        if binding_error is None and frozen_qe is None:
                            binding_error = f"frozen quarantine entry #{frozen_qid} is missing"

                        try:
                            meta = json.loads(it.metadata_json or "{}")
                        except Exception:
                            meta = None
                            if binding_error is None:
                                binding_error = "malformed metadata_json"
                        if meta is not None and not isinstance(meta, dict):
                            meta = None
                            if binding_error is None:
                                binding_error = "metadata_json is not an object"

                        if binding_error is None and isinstance(meta, dict) and frozen_qe is not None:
                            binding_error = _gate6a_restore_binding_error(
                                plan_metadata=recovery_plan_meta,
                                metadata=meta,
                                entry_id=int(frozen_qid),
                                source_path=it.source_path,
                                target_path=it.target_path,
                                entry=frozen_qe,
                                item_id=int(it.id),
                                frozen_expected={
                                    "device": it.expected_device,
                                    "inode": it.expected_inode,
                                    "size": it.expected_size,
                                    "mtime_ns": it.expected_mtime_ns,
                                    "content_hash": it.expected_hash,
                                },
                            )

                        if binding_error is not None:
                            gate6a_authority_loss[int(it.id)] = (
                                frozen_qid,
                                frozen_source,
                                frozen_target,
                                f"Gate6-A restoring recovery lost frozen restore authority: {binding_error}",
                            )
                            # Never select a transactional recovery target from mutable qid/source.
                            # The DB-only authority-loss convergence below marks the frozen owner
                            # conflict and emits one terminal failed audit without filesystem mutation.
                            continue

                        qe = frozen_qe
'''
handlers = handlers[:block_start] + new_recovery_block + handlers[block_end:]

old_unpack = '                    qentry_id, fallback_reason = authority_loss\n'
new_unpack = '                    qentry_id, frozen_source, frozen_target, fallback_reason = authority_loss\n'
assert handlers.count(old_unpack) == 1, handlers.count(old_unpack)
handlers = handlers.replace(old_unpack, new_unpack, 1)

old_result_path = '                        result_path = it.target_path\n'
new_result_path = '                        result_path = frozen_target\n'
assert handlers.count(old_result_path) >= 1
handlers = handlers.replace(old_result_path, new_result_path, 1)

old_audit = '''                            operation="restore",
                            path=it.source_path,
                            result=result,
                            details_json=json.dumps({
                                "plan_id": plan_id,
                                "item_id": it.id,
                                "task_id": job.id,
                                "quarantine_entry_id": qentry_id,
                                "reason": reason,
                                "target": it.target_path,
                                "result_path": result_path,
                                "conflict_policy": plan_meta.get("conflict_policy"),
                                "recovery_phase": "gate6a_restore_authority_loss",
'''
new_audit = '''                            operation="restore",
                            path=frozen_source or it.source_path,
                            result=result,
                            details_json=json.dumps({
                                "plan_id": plan_id,
                                "item_id": it.id,
                                "task_id": job.id,
                                "quarantine_entry_id": qentry_id,
                                "reason": reason,
                                "target": frozen_target,
                                "result_path": result_path,
                                "conflict_policy": plan_meta.get("conflict_policy"),
                                "recovery_phase": "gate6a_restore_authority_loss",
'''
assert handlers.count(old_audit) == 1, handlers.count(old_audit)
handlers = handlers.replace(old_audit, new_audit, 1)
handlers_path.write_text(handlers)

reconcile_path = Path("app/quarantine/reconcile.py")
reconcile = reconcile_path.read_text()
resolver_start = reconcile.index("def _resolve_gate6a_restore_target(")
resolver_end = reconcile.index("\n\ndef _reconcile_restoring(", resolver_start)
new_resolver = '''def _resolve_gate6a_restore_target(session: Session, entry_id: int) -> tuple[Path | None, str | None]:
    # Recover and re-validate plan-level frozen Gate6-A restore authority.
    entry = session.get(QuarantineEntry, entry_id)
    entry_quarantine_path = entry.quarantine_path if entry is not None else None
    matches: list[tuple[BatchPlanItem, dict]] = []
    unresolved_gate6a_items: list[tuple[int, str]] = []
    executing_restores = list(session.scalars(
        select(BatchPlanItem).where(
            BatchPlanItem.operation == "restore",
            BatchPlanItem.state == "executing",
        )
    ))

    def mutable_row_mentions_entry(item: BatchPlanItem) -> bool:
        if entry_quarantine_path and item.source_path == entry_quarantine_path:
            return True
        try:
            metadata = json.loads(item.metadata_json or "{}")
        except Exception:
            return False
        if not isinstance(metadata, dict):
            return False
        undo_meta = metadata.get("undo")
        if not isinstance(undo_meta, dict):
            undo_meta = {}
        raw_qid = metadata.get("quarantine_entry_id")
        if raw_qid is None:
            raw_qid = undo_meta.get("quarantine_entry_id")
        try:
            return raw_qid is not None and int(raw_qid) == entry_id
        except (TypeError, ValueError):
            return False

    for item in executing_restores:
        plan = session.get(BatchPlan, item.plan_id)
        if plan is None or plan.kind != "quarantine-bulk-restore":
            continue

        try:
            plan_meta = json.loads(plan.metadata_json or "{}")
        except Exception:
            plan_meta = None
        if not isinstance(plan_meta, dict):
            if mutable_row_mentions_entry(item):
                unresolved_gate6a_items.append((int(item.id), "malformed plan metadata_json"))
            continue

        authority_map = plan_meta.get("restore_item_authority")
        authority = authority_map.get(str(item.id)) if isinstance(authority_map, dict) else None
        if not isinstance(authority, dict):
            if mutable_row_mentions_entry(item):
                unresolved_gate6a_items.append((int(item.id), "missing restore_item_authority"))
            continue

        raw_frozen_qid = authority.get("quarantine_entry_id")
        if not isinstance(raw_frozen_qid, int) or isinstance(raw_frozen_qid, bool) or raw_frozen_qid <= 0:
            if mutable_row_mentions_entry(item):
                unresolved_gate6a_items.append((int(item.id), "invalid frozen quarantine_entry_id authority"))
            continue
        frozen_qid = int(raw_frozen_qid)
        if frozen_qid != entry_id:
            continue

        try:
            metadata = json.loads(item.metadata_json or "{}")
        except Exception:
            unresolved_gate6a_items.append((int(item.id), "malformed metadata_json"))
            continue
        if not isinstance(metadata, dict):
            unresolved_gate6a_items.append((int(item.id), "metadata_json is not an object"))
            continue

        frozen_entry = session.get(QuarantineEntry, frozen_qid)
        if frozen_entry is None:
            unresolved_gate6a_items.append((int(item.id), f"frozen quarantine entry #{frozen_qid} is missing"))
            continue

        from app.quarantine.bulk_lifecycle import _gate6a_restore_binding_error
        binding_error = _gate6a_restore_binding_error(
            plan_metadata=plan_meta,
            metadata=metadata,
            entry_id=frozen_qid,
            source_path=item.source_path,
            target_path=item.target_path,
            entry=frozen_entry,
            item_id=int(item.id),
            frozen_expected={
                "device": item.expected_device,
                "inode": item.expected_inode,
                "size": item.expected_size,
                "mtime_ns": item.expected_mtime_ns,
                "content_hash": item.expected_hash,
            },
        )
        if binding_error is not None:
            unresolved_gate6a_items.append((int(item.id), binding_error))
            continue

        matches.append((item, authority))

    if unresolved_gate6a_items:
        details = ", ".join(
            f"item #{item_id}: {reason}" for item_id, reason in unresolved_gate6a_items
        )
        return None, (
            "Gate6-A restoring recovery lost frozen restore authority because an executing "
            f"bulk-restore binding no longer matches plan authority ({details})"
        )

    if not matches:
        return None, None
    if len(matches) != 1:
        return None, (
            "Gate6-A restoring recovery found ambiguous executing frozen restore authority "
            f"for quarantine entry #{entry_id}"
        )

    item, authority = matches[0]
    frozen_target = authority.get("target_path")
    if not isinstance(frozen_target, str) or not frozen_target:
        return None, (
            "Gate6-A restoring recovery is missing frozen target_path "
            f"for plan item #{item.id}"
        )
    if item.target_path != frozen_target:
        return None, (
            "Gate6-A restoring recovery lost frozen restore authority: "
            f"target_path mismatch for plan item #{item.id}"
        )
    return Path(frozen_target), None
'''
reconcile = reconcile[:resolver_start] + new_resolver + reconcile[resolver_end:]
reconcile_path.write_text(reconcile)

ast.parse(handlers_path.read_text())
ast.parse(reconcile_path.read_text())
