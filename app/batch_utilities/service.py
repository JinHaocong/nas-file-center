import math
from pathlib import Path
from typing import Any

from app.config import Settings
from app.batch_utilities.compiler import (
    BatchUtilitySafetySnapshot,
    BatchUtilityCompilation,
)
from app.batch_utilities.digest import (
    BATCH_UTILITY_ENGINE_VERSION,
    compute_preview_digest,
)


def capture_batch_utility_safety_snapshot(settings: Settings) -> BatchUtilitySafetySnapshot:
    protect_last_file = getattr(settings, "protect_last_file", True)
    allowed_roots = tuple(Path(r).resolve() for r in settings.allowed_roots)
    quarantine_root = Path(settings.quarantine_root).resolve() if settings.quarantine_root else None

    effective_policy = {
        "protect_last_file": protect_last_file,
        "allowed_roots": [str(r) for r in allowed_roots],
        "quarantine_root": str(quarantine_root) if quarantine_root else None,
    }

    return BatchUtilitySafetySnapshot(
        protect_last_file=protect_last_file,
        allowed_roots=allowed_roots,
        quarantine_root=quarantine_root,
        effective_policy=effective_policy,
    )


def build_batch_utility_preview_response(
    compilation: BatchUtilityCompilation,
    safety_snapshot: BatchUtilitySafetySnapshot,
    *,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    intents_dicts = [
        {
            "sequence": intent.sequence,
            "operation": intent.operation,
            "source_path": intent.source_path,
            "target_path": intent.target_path,
            "keep_path": intent.keep_path,
            "expected_size": intent.expected_size,
            "expected_device": intent.expected_device,
            "expected_inode": intent.expected_inode,
            "expected_mtime_ns": intent.expected_mtime_ns,
            "expected_hash": intent.expected_hash,
            "metadata_json": intent.metadata_json,
        }
        for intent in compilation.intents
    ]

    preview_digest = compute_preview_digest(
        action_config_digest=compilation.action_config_digest,
        source_snapshot_digest=compilation.source_snapshot_digest,
        effective_safety_policy=safety_snapshot.effective_policy,
        decision_rows=compilation.rows,
        intents=intents_dicts,
    )

    total_items = len(compilation.rows)
    total_pages = 0 if total_items == 0 else math.ceil(total_items / page_size)
    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size
    paged_items = compilation.rows[start_idx:end_idx]

    return {
        "utility_action": "quarantine_filtered",
        "utility_engine_version": BATCH_UTILITY_ENGINE_VERSION,
        "preview_source": "index-readonly-safety",
        "live_filesystem_verified": False,
        "matched_count": compilation.matched_count,
        "matched_bytes": compilation.matched_bytes,
        "candidate_count": compilation.candidate_count,
        "candidate_bytes": compilation.candidate_bytes,
        "planned_operations_count": compilation.planned_operations_count,
        "skipped_count": compilation.skipped_count,
        "safety_excluded_count": compilation.safety_excluded_count,
        "blocking_conflict_count": compilation.blocking_conflict_count,
        "expected_reclaim_bytes": compilation.expected_reclaim_bytes,
        "action_config_digest": compilation.action_config_digest,
        "source_snapshot_digest": compilation.source_snapshot_digest,
        "preview_digest": preview_digest,
        "effective_safety_policy": safety_snapshot.effective_policy,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "items": list(paged_items),
    }
