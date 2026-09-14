from pathlib import Path

path = Path("app/tasks/handlers.py")
text = path.read_text()
old = '''        session.refresh(q_entry)
        if q_entry.state == "purging" and q_entry.tx_phase == "purging":
            item.state = "planned"
            item.reason = None
            return

        if q_entry.state != "purged" or q_entry.tx_phase != "purged":
'''
new = '''        session.refresh(q_entry)
        if q_entry.state == "active" and q_entry.tx_phase == "active":
            recovery_reason = "reconciled transactional purge after crash before irreversible intent"
            existing_recovery_audits = list(session.scalars(
                select(AuditEvent).where(
                    AuditEvent.operation == "quarantine_purge",
                    AuditEvent.result == "recovered",
                )
            ))
            already_recovery_audited = False
            for event in existing_recovery_audits:
                try:
                    details = json.loads(event.details_json or "{}")
                except Exception:
                    continue
                if (
                    isinstance(details, dict)
                    and details.get("plan_id") == plan_id
                    and details.get("item_id") == item.id
                    and details.get("quarantine_entry_id") == q_entry_id
                    and details.get("recovery_phase") == "pre_intent"
                ):
                    already_recovery_audited = True
                    break
            if not already_recovery_audited:
                session.add(AuditEvent(
                    operation="quarantine_purge",
                    path=item.source_path,
                    result="recovered",
                    details_json=json.dumps({
                        "plan_id": plan_id,
                        "item_id": item.id,
                        "task_id": job_id,
                        "quarantine_entry_id": q_entry_id,
                        "preview_digest": meta.get("preview_digest"),
                        "recovery_phase": "pre_intent",
                        "reason": recovery_reason,
                    }, ensure_ascii=False),
                ))
            item.state = "planned"
            item.reason = None
            return

        if q_entry.state == "purging" and q_entry.tx_phase == "purging":
            item.state = "planned"
            item.reason = None
            return

        if q_entry.state != "purged" or q_entry.tx_phase != "purged":
'''
count = text.count(old)
if count != 1:
    raise SystemExit(f"B8 target block expected exactly once, got {count}")
path.write_text(text.replace(old, new, 1))
