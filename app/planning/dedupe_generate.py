from __future__ import annotations

from dataclasses import dataclass
import json

from app.planning.dedupe_preview import DedupePreviewCompilation, derive_canonical_top_level_dir


@dataclass(frozen=True)
class DedupeDraftIntent:
    sequence: int
    operation: str
    source_path: str
    keep_path: str
    expected_size: int
    expected_device: int
    expected_inode: int
    expected_mtime_ns: int
    expected_hash: str | None
    metadata_json: str


def build_advanced_dedupe_draft_intents(
    compilation: DedupePreviewCompilation,
    *,
    protect_last_file: bool,
) -> tuple[DedupeDraftIntent, ...]:
    intents: list[DedupeDraftIntent] = []

    for group in compilation.groups:
        if group.status != "actionable":
            continue
        if group.recommended_keep is None:
            raise ValueError("Actionable dedupe group is missing recommended KEEP member")

        keep_path = group.recommended_keep.absolute_path
        keep_explain = next(
            (member for member in group.members if member.recommended_keep),
            None,
        )
        if keep_explain is None:
            raise ValueError("Actionable dedupe group is missing KEEP explanation")

        members_by_path = {member.absolute_path: member for member in group.members}
        for cleanup_path in group.quarantine_candidates:
            member = members_by_path.get(cleanup_path)
            if member is None:
                raise ValueError(f"Quarantine candidate is absent from group decision rows: {cleanup_path}")

            metadata = {
                "scan_job_id": compilation.scan_job_id,
                "group_provenance_id": group.group_provenance_id,
                "group_decision_fingerprint": group.group_decision_fingerprint,
                "scan_root_index": member.scan_root_index,
                "scan_root_path": member.scan_root_path,
                "keep_scan_root_index": group.recommended_keep.scan_root_index,
                "keep_scan_root_path": group.recommended_keep.scan_root_path,
                "selection_reason": keep_explain.selection_reason,
            }
            if protect_last_file:
                metadata["protected_dir"] = derive_canonical_top_level_dir(
                    member.scan_root_path,
                    member.relative_path,
                )

            intents.append(DedupeDraftIntent(
                sequence=len(intents) + 1,
                operation="quarantine",
                source_path=cleanup_path,
                keep_path=keep_path,
                expected_size=group.file_size,
                expected_device=0,
                expected_inode=0,
                expected_mtime_ns=0,
                expected_hash=None,
                metadata_json=json.dumps(metadata, ensure_ascii=False, sort_keys=True),
            ))

    return tuple(intents)
