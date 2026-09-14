from __future__ import annotations

from pathlib import Path
import re
import textwrap


def replace_regex_once(text: str, pattern: str, replacement: str, *, label: str) -> str:
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.S)
    if count != 1:
        raise SystemExit(f"{label}: expected one regex match, got {count}")
    return updated


def replace_exact_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one exact match, got {count}")
    return text.replace(old, new, 1)


purge_path = Path("app/quarantine/purge.py")
purge = purge_path.read_text()

build_fn = textwrap.dedent(
    '''
    def build_purge_topology_manifest(
        entry: Any,
        quarantine_root: Path | str,
        *,
        owner_lookup: Callable[[int], Any | None] | None = None,
    ) -> dict[str, Any]:
        """Build the read-only Gate6-A transactional purge topology manifest."""
        manifest = _build_preview_purge_topology_manifest(
            entry,
            quarantine_root,
            owner_lookup=owner_lookup,
        )
        manifest["frozen_payload_identity"] = {
            "device": entry.device,
            "inode": entry.inode,
            "size": entry.size,
            "mtime_ns": entry.mtime_ns,
            "content_hash": str(entry.content_hash or "").lower(),
        }
        return manifest
    '''
).lstrip()
purge = replace_regex_once(
    purge,
    r"def build_purge_topology_manifest\(.*?(?=\n\ndef validate_purge_topology_manifest)",
    build_fn.rstrip(),
    label="purge build manifest",
)

identity_helper = textwrap.dedent(
    '''

    def _require_frozen_payload_identity(
        frozen_manifest: dict[str, Any],
    ) -> tuple[int, int, int, int, str]:
        raw = frozen_manifest.get("frozen_payload_identity")
        if not isinstance(raw, dict):
            raise StateConflictError("PURGE_FROZEN_IDENTITY_MISSING: frozen payload identity is required")
        required = ("device", "inode", "size", "mtime_ns", "content_hash")
        if any(raw.get(key) is None for key in required):
            raise StateConflictError("PURGE_FROZEN_IDENTITY_MISSING: frozen payload identity is incomplete")
        try:
            device = int(raw["device"])
            inode = int(raw["inode"])
            size = int(raw["size"])
            mtime_ns = int(raw["mtime_ns"])
        except (TypeError, ValueError) as exc:
            raise StateConflictError("PURGE_FROZEN_IDENTITY_MISSING: frozen payload identity is invalid") from exc
        content_hash = str(raw.get("content_hash") or "").lower()
        if not content_hash:
            raise StateConflictError("PURGE_FROZEN_IDENTITY_MISSING: frozen payload hash is required")
        return device, inode, size, mtime_ns, content_hash
    '''
)
classify_marker = "\n\ndef classify_cross_entry_alias_owner("
if purge.count(classify_marker) != 1:
    raise SystemExit("purge classify marker is not unique")
purge = purge.replace(classify_marker, identity_helper.rstrip() + classify_marker, 1)

begin_fn = textwrap.dedent(
    '''
    def _begin_transactional_purge_intent(
        session_factory: Any,
        entry_id: int,
        worker_id: str,
        frozen_manifest: dict[str, Any] | None = None,
        quarantine_root: Path | str | None = None,
    ) -> None:
        """Commit Gate6-A irreversible purge intent before any filesystem capture syscall."""
        with session_factory() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            assert_active_worker_lease(session, worker_id)
            entry = session.get(QuarantineEntry, entry_id)
            if entry is None:
                session.rollback()
                raise StateConflictError(f"Quarantine entry #{entry_id} not found")
            if entry.state != "active" or entry.tx_phase != "active":
                state = entry.state
                tx_phase = entry.tx_phase
                session.rollback()
                raise StateConflictError(
                    f"Quarantine entry #{entry_id} must still be active before purge "
                    f"(state={state}, tx_phase={tx_phase})"
                )
            if frozen_manifest is None:
                session.rollback()
                raise StateConflictError("PURGE_FROZEN_IDENTITY_MISSING: frozen purge authority is required")
            expected_identity = _require_frozen_payload_identity(frozen_manifest)
            current_identity = (
                int(entry.device or 0),
                int(entry.inode or 0),
                int(entry.size or 0),
                int(entry.mtime_ns or 0),
                str(entry.content_hash or "").lower(),
            )
            if current_identity != expected_identity:
                session.rollback()
                raise StateConflictError(
                    f"PURGE_FROZEN_IDENTITY_CHANGED: quarantine entry #{entry_id} identity changed after Freeze"
                )
            if quarantine_root is not None:
                ownership_reason = _intent_time_purge_ownership_reason(
                    session,
                    entry,
                    frozen_manifest,
                    Path(quarantine_root),
                )
                if ownership_reason is not None:
                    session.rollback()
                    raise StateConflictError(
                        f"{ownership_reason}: purge ownership changed before irreversible intent "
                        f"for quarantine entry #{entry_id}"
                    )
            entry.state = "purging"
            entry.tx_phase = "purging"
            session.commit()
    '''
).lstrip()
purge = replace_regex_once(
    purge,
    r"def _begin_transactional_purge_intent\(.*?(?=\n\ndef _allocate_transactional_purge_attempt)",
    begin_fn.rstrip(),
    label="purge begin intent",
)

mutable_identity = textwrap.dedent(
    '''
            generation = int(entry.active_attempt_generation or 0)
            expected_device = entry.device
            expected_inode = entry.inode
            expected_size = entry.size
            expected_mtime_ns = entry.mtime_ns
            expected_hash = (entry.content_hash or "").lower()

        if generation <= 0 or not expected_hash:
    '''
).lstrip("\n")
frozen_identity = textwrap.dedent(
    '''
            generation = int(entry.active_attempt_generation or 0)

        expected_device, expected_inode, expected_size, expected_mtime_ns, expected_hash = (
            _require_frozen_payload_identity(frozen_manifest)
        )
        if generation <= 0:
    '''
).lstrip("\n")
count = purge.count(mutable_identity)
if count != 2:
    raise SystemExit(f"purge mutable identity reads: expected two matches, got {count}")
purge = purge.replace(mutable_identity, frozen_identity)

terminal_marker = '        entry.state = "purged"\n'
if purge.count(terminal_marker) != 1:
    raise SystemExit(f"purge terminal marker count={purge.count(terminal_marker)}")
terminal_check = textwrap.dedent(
    '''
            current_identity = (
                int(entry.device or 0),
                int(entry.inode or 0),
                int(entry.size or 0),
                int(entry.mtime_ns or 0),
                str(entry.content_hash or "").lower(),
            )
            if current_identity != (
                expected_device,
                expected_inode,
                expected_size,
                expected_mtime_ns,
                expected_hash,
            ):
                session.rollback()
                raise StateConflictError(
                    f"PURGE_FROZEN_IDENTITY_CHANGED: quarantine entry #{entry_id} identity changed before terminal purge commit"
                )
    '''
).lstrip("\n")
purge = purge.replace(terminal_marker, terminal_check + terminal_marker, 1)
purge_path.write_text(purge)

executor_path = Path("app/execution/executor.py")
executor = executor_path.read_text()
executor_block = textwrap.indent(
    textwrap.dedent(
        '''
        if item.operation == "quarantine_purge":
            if not session_factory or not worker_id or not quarantine_entry_id or purge_manifest is None:
                return ItemResult(
                    "failed",
                    "EOPNOTSUPP: quarantine purge requires worker authority, session_factory, quarantine_entry_id, and frozen purge manifest",
                )
            if (
                item.expected_device is None
                or item.expected_inode is None
                or item.expected_size is None
                or item.expected_mtime_ns is None
                or not item.expected_hash
            ):
                return ItemResult(
                    "failed",
                    "PURGE_FROZEN_IDENTITY_MISSING: BatchPlanItem.expected_* is required",
                )
            frozen_identity = (
                int(item.expected_device),
                int(item.expected_inode),
                int(item.expected_size),
                int(item.expected_mtime_ns),
                str(item.expected_hash).lower(),
            )
            frozen_purge_authority = dict(purge_manifest)
            frozen_purge_authority["frozen_payload_identity"] = {
                "device": frozen_identity[0],
                "inode": frozen_identity[1],
                "size": frozen_identity[2],
                "mtime_ns": frozen_identity[3],
                "content_hash": frozen_identity[4],
            }

            from app.models import QuarantineEntry

            with session_factory() as session:
                q_entry = session.get(QuarantineEntry, quarantine_entry_id)
                if q_entry is None:
                    return ItemResult(
                        "failed",
                        f"PURGE_FROZEN_IDENTITY_CHANGED: quarantine entry #{quarantine_entry_id} no longer exists",
                    )
                current_identity = (
                    int(q_entry.device or 0),
                    int(q_entry.inode or 0),
                    int(q_entry.size or 0),
                    int(q_entry.mtime_ns or 0),
                    str(q_entry.content_hash or "").lower(),
                )
                if current_identity != frozen_identity:
                    return ItemResult(
                        "failed",
                        f"PURGE_FROZEN_IDENTITY_CHANGED: quarantine entry #{quarantine_entry_id} identity changed after Freeze",
                    )
            try:
                from app.quarantine.purge import (
                    destroy_transactional_purge_capture,
                    execute_transactional_purge_capture,
                )
                execute_transactional_purge_capture(
                    session_factory,
                    quarantine_entry_id,
                    worker_id,
                    frozen_purge_authority,
                    quarantine_root,
                    list(allowed_roots),
                )
                destroy_transactional_purge_capture(
                    session_factory,
                    quarantine_entry_id,
                    worker_id,
                    frozen_purge_authority,
                    quarantine_root,
                    list(allowed_roots),
                )
            except Exception as exc:
                return ItemResult("failed", str(exc))
            return ItemResult("completed", "purged")
        '''
    ).lstrip(),
    "    ",
)
executor = replace_regex_once(
    executor,
    r'    if item\.operation == "quarantine_purge":\n.*?(?=    if item\.operation not in )',
    executor_block,
    label="executor quarantine_purge block",
)
executor_path.write_text(executor)

executor_tests_path = Path("tests/test_gate6a_transactional_purge_executor.py")
executor_tests = executor_tests_path.read_text()
authorized_old = '''        OperationItem(sequence=1, operation="quarantine_purge", source=public_view),
        allowed_roots=[data],
        allow_mutation=True,
        allow_delete=True,
        quarantine_root=quarantine_root,
        plan_id="gate6a-purge-authorized",'''
authorized_new = '''        OperationItem(
            sequence=1,
            operation="quarantine_purge",
            source=public_view,
            expected_device=st.st_dev,
            expected_inode=st.st_ino,
            expected_size=st.st_size,
            expected_mtime_ns=st.st_mtime_ns,
            expected_hash=hashlib.sha256(payload).hexdigest(),
        ),
        allowed_roots=[data],
        allow_mutation=True,
        allow_delete=True,
        quarantine_root=quarantine_root,
        plan_id="gate6a-purge-authorized",'''
executor_tests = replace_exact_once(
    executor_tests,
    authorized_old,
    authorized_new,
    label="executor authorized test",
)
owner_old = '''        OperationItem(sequence=1, operation="quarantine_purge", source=public_view),
        allowed_roots=[data],
        allow_mutation=True,
        allow_delete=True,
        quarantine_root=quarantine_root,
        plan_id="gate6a-purge-owner-race",'''
owner_new = '''        OperationItem(
            sequence=1,
            operation="quarantine_purge",
            source=public_view,
            expected_device=st.st_dev,
            expected_inode=st.st_ino,
            expected_size=st.st_size,
            expected_mtime_ns=st.st_mtime_ns,
            expected_hash=payload_hash,
        ),
        allowed_roots=[data],
        allow_mutation=True,
        allow_delete=True,
        quarantine_root=quarantine_root,
        plan_id="gate6a-purge-owner-race",'''
executor_tests = replace_exact_once(
    executor_tests,
    owner_old,
    owner_new,
    label="executor owner-race test",
)
executor_tests_path.write_text(executor_tests)
