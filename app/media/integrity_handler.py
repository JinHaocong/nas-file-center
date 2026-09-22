from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import func, select, text

from app.media.catalog import validate_media_root_keys
from app.media.integrity import IntegrityCheckResult, verify_or_establish_integrity_baseline
from app.models import IndexedPath, MediaAsset, WorkJob, utcnow
from app.path_safety import UnsafePathError, require_allowed_path
from app.tasks.handlers_base import TaskHandler, register_handler


_VERIFY_BATCH_SIZE = 25


def _checkpoint_state(job: WorkJob) -> dict:
    try:
        value = json.loads(job.checkpoint_json or "{}")
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _unsafe_result(detail: str) -> IntegrityCheckResult:
    return IntegrityCheckResult(
        status="unknown",
        reason_code="PATH_UNSAFE",
        detail=detail,
    )


@register_handler
class MediaIntegrityVerifyHandler(TaskHandler):
    job_type = "media-integrity-verify"
    supports_pause = True
    supports_cancel = True
    supports_retry = True
    supports_resume = True

    def run(self, job: WorkJob, context, settings) -> None:
        # Imported lazily to avoid recovery/handler import cycles.
        from app.tasks.recovery import assert_active_worker_lease

        state = json.loads(job.state_json or "{}")
        root_keys_raw = state.get("root_keys")
        if not isinstance(root_keys_raw, list) or not all(isinstance(x, str) for x in root_keys_raw):
            raise ValueError("media-integrity-verify state missing root_keys")

        root_keys = validate_media_root_keys(context.SessionLocal, settings, root_keys_raw)
        saved = _checkpoint_state(job)
        last_media_asset_id = int(saved.get("last_media_asset_id") or 0)
        processed = int(saved.get("processed") or 0)

        with context.SessionLocal() as session:
            total = session.scalar(
                select(func.count(MediaAsset.id))
                .select_from(MediaAsset)
                .join(IndexedPath, IndexedPath.id == MediaAsset.indexed_path_id)
                .where(IndexedPath.root_key.in_(root_keys))
            ) or 0

        def write_checkpoint(message: str) -> None:
            context.checkpoint(
                progress_current=min(processed, int(total)),
                progress_total=int(total),
                progress_message=message,
                checkpoint_data={
                    "schema_version": 1,
                    "phase": "verifying",
                    "root_keys": root_keys,
                    "last_media_asset_id": last_media_asset_id,
                    "processed": processed,
                },
            )

        write_checkpoint(f"Verifying media integrity ({processed}/{total})...")

        while True:
            with context.SessionLocal() as session:
                rows = list(
                    session.execute(
                        select(MediaAsset, IndexedPath)
                        .join(IndexedPath, IndexedPath.id == MediaAsset.indexed_path_id)
                        .where(
                            IndexedPath.root_key.in_(root_keys),
                            MediaAsset.id > last_media_asset_id,
                        )
                        .order_by(MediaAsset.id.asc())
                        .limit(_VERIFY_BATCH_SIZE)
                    ).all()
                )

            if not rows:
                break

            results: list[tuple[int, IntegrityCheckResult]] = []
            for asset, indexed in rows:
                source = Path(indexed.absolute_path)

                def hash_checkpoint() -> None:
                    write_checkpoint(f"Hashing {indexed.basename}")

                try:
                    # Validate the parent only. The final component is kept
                    # lexical so a source symlink cannot be silently followed.
                    safe_parent = require_allowed_path(source.parent, settings.allowed_roots)
                    safe_source = safe_parent / source.name
                    result = verify_or_establish_integrity_baseline(
                        safe_source,
                        indexed_device=int(indexed.device),
                        indexed_inode=int(indexed.inode),
                        indexed_size=int(indexed.size),
                        indexed_mtime_ns=int(indexed.mtime_ns),
                        baseline_sha256=asset.verification_sha256,
                        baseline_device=asset.verification_device,
                        baseline_inode=asset.verification_inode,
                        baseline_size=asset.verification_size,
                        baseline_mtime_ns=asset.verification_mtime_ns,
                        checkpoint=hash_checkpoint,
                    )
                except UnsafePathError as exc:
                    result = _unsafe_result(str(exc))

                results.append((int(asset.id), result))

            with context.SessionLocal() as session:
                session.execute(text("BEGIN IMMEDIATE"))
                if context.worker_id is not None:
                    assert_active_worker_lease(session, context.worker_id, now=utcnow())

                now = utcnow()
                for asset_id, result in results:
                    asset = session.get(MediaAsset, asset_id)
                    if asset is None:
                        continue

                    asset.verification_status = result.status
                    asset.verification_reason_code = result.reason_code
                    asset.verification_detail = result.detail
                    asset.verification_observed_sha256 = result.observed_sha256
                    asset.verification_checked_at = now
                    asset.updated_at = now

                    if result.baseline_sha256 is not None:
                        # Baselines are only minted when none exists. The
                        # verifier never overwrites an existing baseline.
                        if asset.verification_sha256 is None:
                            asset.verification_sha256 = result.baseline_sha256
                            asset.verification_device = result.baseline_device
                            asset.verification_inode = result.baseline_inode
                            asset.verification_size = result.baseline_size
                            asset.verification_mtime_ns = result.baseline_mtime_ns

                session.commit()

            processed += len(rows)
            last_media_asset_id = int(rows[-1][0].id)
            write_checkpoint(f"Verified {processed}/{total} media files")

        context.checkpoint(
            progress_current=int(total),
            progress_total=int(total),
            progress_message="Media integrity verification completed",
            checkpoint_data={
                "schema_version": 1,
                "phase": "completed",
                "root_keys": root_keys,
                "last_media_asset_id": last_media_asset_id,
                "processed": int(total),
            },
        )
