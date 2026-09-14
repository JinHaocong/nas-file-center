from pathlib import Path
import ast

handlers_path = Path("app/tasks/handlers.py")
handlers = handlers_path.read_text()

start = handlers.index('                    if is_gate6a_restore_recovery:\n', handlers.index('class BatchPlanExecuteHandler'))
end_marker = '''                    else:
                        meta = json.loads(it.metadata_json or "{}")
                        qid = meta.get("quarantine_entry_id") or meta.get("undo", {}).get("quarantine_entry_id")
                        qe = session.get(QuarantineEntry, int(qid)) if qid else None
'''
end = handlers.index(end_marker, start)

new_block = '''                    if is_gate6a_restore_recovery:
                        from app.quarantine.bulk_lifecycle import _gate6a_restore_binding_error

                        try:
                            recovery_plan_meta = json.loads(recovery_plan.metadata_json or "{}")
                        except Exception:
                            recovery_plan_meta = {}
                        if not isinstance(recovery_plan_meta, dict):
                            recovery_plan_meta = {}
                        authority_map = recovery_plan_meta.get("restore_item_authority")

                        if isinstance(authority_map, dict):
                            authority = authority_map.get(str(it.id))
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
                                # Strict plans must never select a transactional recovery target
                                # from mutable qid/source after frozen authority no longer matches.
                                continue

                            qe = frozen_qe
                        else:
                            # Compatibility for durable executing plans created before stable
                            # per-item restore_item_authority existed. Mutable qid/source are used
                            # only to scope/fail-close the legacy recovery, never to override a
                            # frozen authority map when one is present.
                            source_qe = session.scalar(
                                select(QuarantineEntry).where(QuarantineEntry.quarantine_path == it.source_path)
                            )
                            try:
                                meta = json.loads(it.metadata_json or "{}")
                            except Exception:
                                meta = None
                                binding_error = "malformed metadata_json"
                            if meta is not None and not isinstance(meta, dict):
                                meta = None
                                binding_error = "metadata_json is not an object"
                            raw_qid = None
                            if isinstance(meta, dict):
                                undo_meta = meta.get("undo")
                                if not isinstance(undo_meta, dict):
                                    undo_meta = {}
                                raw_qid = meta.get("quarantine_entry_id")
                                if raw_qid is None:
                                    raw_qid = undo_meta.get("quarantine_entry_id")
                                if raw_qid is None:
                                    binding_error = "missing quarantine_entry_id"
                            bound_qid = None
                            if raw_qid is not None:
                                try:
                                    bound_qid = int(raw_qid)
                                except (TypeError, ValueError):
                                    binding_error = "invalid quarantine_entry_id"
                            if bound_qid is not None:
                                qe = session.get(QuarantineEntry, bound_qid)
                                if qe is None:
                                    binding_error = f"quarantine entry #{bound_qid} is missing"
                                elif qe.quarantine_path != it.source_path:
                                    binding_error = "quarantine_entry_id disagrees with frozen source_path owner"
                            if binding_error:
                                affected_qe = source_qe
                                gate6a_authority_loss[int(it.id)] = (
                                    int(affected_qe.id) if affected_qe is not None else None,
                                    it.source_path,
                                    it.target_path,
                                    f"Gate6-A restoring recovery lost legacy restore authority: {binding_error}",
                                )
                                if affected_qe and (
                                    affected_qe.tx_phase is not None
                                    or affected_qe.authoritative_anchor_path is not None
                                ):
                                    tx_entries_to_reconcile.append(int(affected_qe.id))
                                continue
'''
handlers = handlers[:start] + new_block + handlers[end:]
handlers_path.write_text(handlers)

reconcile_path = Path("app/quarantine/reconcile.py")
reconcile = reconcile_path.read_text()
resolver_start = reconcile.index("def _resolve_gate6a_restore_target(")
resolver_end = reconcile.index("\n\ndef _reconcile_restoring(", resolver_start)
new_resolver = '''def _resolve_gate6a_restore_target(session: Session, entry_id: int) -> tuple[Path | None, str | None]:
    """Recover Gate6-A restore target, enforcing stable authority when available."""
    entry = session.get(QuarantineEntry, entry_id)
    entry_quarantine_path = entry.quarantine_path if entry is not None else None
    matches: list[tuple[BatchPlanItem, str]] = []
    unresolved_gate6a_items: list[tuple[int, str]] = []
    executing_restores = list(session.scalars(
        select(BatchPlanItem).where(
            BatchPlanItem.operation == "restore",
            BatchPlanItem.state == "executing",
        )
    ))

    def owns_legacy_source(item: BatchPlanItem) -> bool:
        return bool(entry_quarantine_path and item.source_path == entry_quarantine_path)

    for item in executing_restores:
        plan = session.get(BatchPlan, item.plan_id)
        if plan is None or plan.kind != "quarantine-bulk-restore":
            continue

        try:
            plan_meta = json.loads(plan.metadata_json or "{}")
        except Exception:
            plan_meta = None
        if not isinstance(plan_meta, dict):
            if owns_legacy_source(item):
                unresolved_gate6a_items.append((int(item.id), "malformed plan metadata_json"))
            continue

        authority_map = plan_meta.get("restore_item_authority")
        if isinstance(authority_map, dict):
            authority = authority_map.get(str(item.id))
            if not isinstance(authority, dict):
                # A strict-plan item without its stable authority is relevant only when the
                # mutable row still names this entry; never poison unrelated qentries.
                if owns_legacy_source(item):
                    unresolved_gate6a_items.append((int(item.id), "missing restore_item_authority"))
                continue

            raw_frozen_qid = authority.get("quarantine_entry_id")
            if not isinstance(raw_frozen_qid, int) or isinstance(raw_frozen_qid, bool) or raw_frozen_qid <= 0:
                if owns_legacy_source(item):
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

            frozen_target = authority.get("target_path")
            if not isinstance(frozen_target, str) or not frozen_target:
                unresolved_gate6a_items.append((int(item.id), "missing frozen target_path"))
                continue
            if item.target_path != frozen_target:
                unresolved_gate6a_items.append((int(item.id), "target_path mismatch"))
                continue
            matches.append((item, frozen_target))
            continue

        # Legacy compatibility: preserve the pre-authority-map recovery contract for
        # already-durable executing plans, including malformed/missing qid fail-closed.
        try:
            meta = json.loads(item.metadata_json or "{}")
        except Exception:
            if owns_legacy_source(item):
                unresolved_gate6a_items.append((int(item.id), "malformed metadata_json"))
            continue
        if not isinstance(meta, dict):
            if owns_legacy_source(item):
                unresolved_gate6a_items.append((int(item.id), "metadata_json is not an object"))
            continue

        undo_meta = meta.get("undo")
        if not isinstance(undo_meta, dict):
            undo_meta = {}
        raw_qid = meta.get("quarantine_entry_id")
        if raw_qid is None:
            raw_qid = undo_meta.get("quarantine_entry_id")
        if raw_qid is None:
            if owns_legacy_source(item):
                unresolved_gate6a_items.append((int(item.id), "missing quarantine_entry_id"))
            continue
        try:
            bound_qid = int(raw_qid)
        except (TypeError, ValueError):
            if owns_legacy_source(item):
                unresolved_gate6a_items.append((int(item.id), "invalid quarantine_entry_id"))
            continue

        if bound_qid == entry_id:
            if entry_quarantine_path and item.source_path != entry_quarantine_path:
                unresolved_gate6a_items.append((int(item.id), "frozen source_path does not match quarantine owner"))
            elif not item.target_path:
                unresolved_gate6a_items.append((int(item.id), "missing legacy target_path"))
            else:
                matches.append((item, item.target_path))
        elif owns_legacy_source(item):
            unresolved_gate6a_items.append((int(item.id), "quarantine_entry_id disagrees with frozen source_path owner"))

    if unresolved_gate6a_items:
        details = ", ".join(
            f"item #{item_id}: {reason}" for item_id, reason in unresolved_gate6a_items
        )
        return None, (
            "Gate6-A restoring recovery lost frozen restore authority because an executing "
            f"bulk-restore binding is unreadable or invalid ({details})"
        )

    if not matches:
        return None, None
    if len(matches) != 1:
        return None, (
            "Gate6-A restoring recovery found ambiguous executing frozen restore authority "
            f"for quarantine entry #{entry_id}"
        )

    _item, target_path = matches[0]
    return Path(target_path), None
'''
reconcile = reconcile[:resolver_start] + new_resolver + reconcile[resolver_end:]
reconcile_path.write_text(reconcile)

ast.parse(handlers_path.read_text())
ast.parse(reconcile_path.read_text())
