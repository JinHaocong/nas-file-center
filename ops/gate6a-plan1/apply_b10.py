from pathlib import Path

DEFERRED_REASON = "PERMANENT_PURGE_DEFERRED_UNSAFE_HARDLINK_SCOPE"

api_path = Path("app/api/quarantine_bulk.py")
api = api_path.read_text()
old_api = '''            if payload.action == "purge":
                def owner_lookup(owner_id: int):
                    owner = session.get(QuarantineEntry, owner_id)
                    if owner is not None:
                        db_identities[owner_id] = quarantine_entry_identity_material(owner)
                    return owner

                manifest = build_purge_topology_manifest(
                    entry,
                    service.settings.quarantine_root,
                    owner_lookup=owner_lookup,
                )
                blockers = manifest["blockers"]
                item = {
                    "entry_id": entry_id,
                    "eligible": not blockers,
                    "reason": blockers[0] if blockers else None,
                    "purge_topology_manifest": manifest,
                }
                items.append(item)
                digest_items.append({**identity, **item})
                continue
'''
new_api = f'''            if payload.action == "purge":
                item = {{
                    "entry_id": entry_id,
                    "eligible": False,
                    "reason": "{DEFERRED_REASON}",
                }}
                items.append(item)
                digest_items.append({{**identity, **item}})
                continue
'''
assert api.count(old_api) == 1, f"expected one API purge preview block, got {api.count(old_api)}"
api_path.write_text(api.replace(old_api, new_api))

executor_path = Path("app/execution/executor.py")
executor = executor_path.read_text()
needle = '''    if item.operation == "quarantine_purge":
        if not session_factory or not worker_id or not quarantine_entry_id or purge_manifest is None:
'''
replacement = '''    if item.operation == "quarantine_purge":
        return ItemResult(
            "failed",
            "EOPNOTSUPP: Gate6-A bulk permanent purge is deferred because safe hard-link ownership scope cannot be proven",
        )
        if not session_factory or not worker_id or not quarantine_entry_id or purge_manifest is None:
'''
assert executor.count(needle) == 1, f"expected one executor purge branch, got {executor.count(needle)}"
executor_path.write_text(executor.replace(needle, replacement))
