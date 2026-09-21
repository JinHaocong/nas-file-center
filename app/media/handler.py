from __future__ import annotations

from dataclasses import replace
import json
from uuid import uuid4

from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.media.catalog import MEDIA_EXTENSIONS, validate_media_root_keys
from app.media.probe import MediaProbeResult, classify_media_kind, probe_media_file
from app.models import IndexedPath, MediaAsset, WorkJob, utcnow
from app.tasks.handlers_base import TaskHandler, register_handler


_ANALYSIS_BATCH_SIZE = 25


def _checkpoint_state(job: WorkJob) -> dict:
    try:
        value = json.loads(job.checkpoint_json or "{}")
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _identity_matches_index(result: MediaProbeResult, row: IndexedPath) -> bool:
    return (
        int(result.observed_device) == int(row.device)
        and int(result.observed_inode) == int(row.inode)
        and int(result.observed_size) == int(row.size)
        and int(result.observed_mtime_ns) == int(row.mtime_ns)
    )


def _unknown_for_index_drift(result: MediaProbeResult) -> MediaProbeResult:
    return replace(
        result,
        integrity_status="unknown",
        integrity_reason_code="INDEX_IDENTITY_CHANGED",
        integrity_detail="live media identity no longer matches the indexed snapshot",
        corrupt_sha256=None,
    )


@register_handler
class MediaAnalysisHandler(TaskHandler):
    job_type = "media-analysis"
    supports_pause = True
    supports_cancel = True
    supports_retry = True
    supports_resume = True

    def run(self, job: WorkJob, context, settings) -> None:
        # Imported lazily to avoid recovery -> handlers -> media.handler -> recovery
        # during application/test module initialization.
        from app.tasks.recovery import assert_active_worker_lease

        state = json.loads(job.state_json or "{}")
        root_keys_raw = state.get("root_keys")
        if not isinstance(root_keys_raw, list) or not all(isinstance(x, str) for x in root_keys_raw):
            raise ValueError("media-analysis state missing root_keys")

        root_keys = validate_media_root_keys(context.SessionLocal, settings, root_keys_raw)
        saved = _checkpoint_state(job)
        last_indexed_path_id = int(saved.get("last_indexed_path_id") or 0)
        processed = int(saved.get("processed") or 0)
        probe_generation = str(saved.get("probe_generation") or uuid4().hex)
        suffixes = sorted(MEDIA_EXTENSIONS)

        with context.SessionLocal() as session:
            total = session.scalar(
                select(func.count(IndexedPath.id)).where(
                    IndexedPath.root_key.in_(root_keys),
                    IndexedPath.is_dir.is_(False),
                    func.lower(IndexedPath.suffix).in_(suffixes),
                )
            ) or 0

        context.checkpoint(
            progress_current=min(processed, int(total)),
            progress_total=int(total),
            progress_message=f"Analyzing media ({processed}/{total})...",
            checkpoint_data={
                "schema_version": 1,
                "phase": "probing",
                "root_keys": root_keys,
                "last_indexed_path_id": last_indexed_path_id,
                "processed": processed,
                "probe_generation": probe_generation,
            },
        )

        # Remove stale media metadata for paths in these roots that are no longer
        # regular media candidates. This is metadata-only and lease fenced.
        with context.SessionLocal() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            if context.worker_id is not None:
                assert_active_worker_lease(session, context.worker_id, now=utcnow())
            stale_index_ids = select(IndexedPath.id).where(
                IndexedPath.root_key.in_(root_keys),
                (
                    IndexedPath.is_dir.is_(True)
                    | func.lower(IndexedPath.suffix).not_in(suffixes)
                ),
            )
            session.execute(
                delete(MediaAsset).where(MediaAsset.indexed_path_id.in_(stale_index_ids))
            )
            session.commit()

        while True:
            with context.SessionLocal() as session:
                rows = list(
                    session.scalars(
                        select(IndexedPath)
                        .where(
                            IndexedPath.root_key.in_(root_keys),
                            IndexedPath.is_dir.is_(False),
                            func.lower(IndexedPath.suffix).in_(suffixes),
                            IndexedPath.id > last_indexed_path_id,
                        )
                        .order_by(IndexedPath.id.asc())
                        .limit(_ANALYSIS_BATCH_SIZE)
                    )
                )

            if not rows:
                break

            pending: list[dict] = []
            for row in rows:
                media_kind = classify_media_kind(row.absolute_path)
                if media_kind is None:
                    last_indexed_path_id = max(last_indexed_path_id, int(row.id))
                    continue

                def probe_checkpoint() -> None:
                    context.checkpoint(
                        progress_current=min(processed, int(total)),
                        progress_total=int(total),
                        progress_message=f"Probing {row.basename}",
                        checkpoint_data={
                            "schema_version": 1,
                            "phase": "probing",
                            "root_keys": root_keys,
                            "last_indexed_path_id": last_indexed_path_id,
                            "processed": processed,
                            "probe_generation": probe_generation,
                        },
                    )

                result = probe_media_file(
                    row.absolute_path,
                    kind=media_kind,
                    ffprobe_binary=settings.ffprobe_binary,
                    checkpoint=probe_checkpoint,
                )
                if (
                    result.observed_device
                    and not _identity_matches_index(result, row)
                ):
                    result = _unknown_for_index_drift(result)

                now = utcnow()
                pending.append(
                    {
                        "indexed_path_id": int(row.id),
                        "media_kind": media_kind,
                        "width": result.width,
                        "height": result.height,
                        "format": result.format,
                        "date_taken": result.date_taken,
                        "camera": result.camera,
                        "orientation": result.orientation,
                        "duration_seconds": result.duration_seconds,
                        "codec": result.codec,
                        "bitrate": result.bitrate,
                        "fps": result.fps,
                        "audio_codec": result.audio_codec,
                        "integrity_status": result.integrity_status,
                        "integrity_reason_code": result.integrity_reason_code,
                        "integrity_detail": result.integrity_detail,
                        "observed_device": int(result.observed_device),
                        "observed_inode": int(result.observed_inode),
                        "observed_size": int(result.observed_size),
                        "observed_mtime_ns": int(result.observed_mtime_ns),
                        "corrupt_sha256": result.corrupt_sha256,
                        "source_scan_generation": row.scan_generation,
                        "probe_generation": probe_generation,
                        "probed_at": now,
                        "updated_at": now,
                    }
                )

            if pending:
                with context.SessionLocal() as session:
                    session.execute(text("BEGIN IMMEDIATE"))
                    if context.worker_id is not None:
                        assert_active_worker_lease(session, context.worker_id, now=utcnow())
                    stmt = sqlite_insert(MediaAsset).values(pending)
                    excluded = stmt.excluded
                    stmt = stmt.on_conflict_do_update(
                        index_elements=[MediaAsset.indexed_path_id],
                        set_={
                            "media_kind": excluded.media_kind,
                            "width": excluded.width,
                            "height": excluded.height,
                            "format": excluded.format,
                            "date_taken": excluded.date_taken,
                            "camera": excluded.camera,
                            "orientation": excluded.orientation,
                            "duration_seconds": excluded.duration_seconds,
                            "codec": excluded.codec,
                            "bitrate": excluded.bitrate,
                            "fps": excluded.fps,
                            "audio_codec": excluded.audio_codec,
                            "integrity_status": excluded.integrity_status,
                            "integrity_reason_code": excluded.integrity_reason_code,
                            "integrity_detail": excluded.integrity_detail,
                            "observed_device": excluded.observed_device,
                            "observed_inode": excluded.observed_inode,
                            "observed_size": excluded.observed_size,
                            "observed_mtime_ns": excluded.observed_mtime_ns,
                            "corrupt_sha256": excluded.corrupt_sha256,
                            "source_scan_generation": excluded.source_scan_generation,
                            "probe_generation": excluded.probe_generation,
                            "probed_at": excluded.probed_at,
                            "updated_at": excluded.updated_at,
                        },
                    )
                    session.execute(stmt)
                    session.commit()

            processed += len(rows)
            last_indexed_path_id = int(rows[-1].id)
            context.checkpoint(
                progress_current=min(processed, int(total)),
                progress_total=int(total),
                progress_message=f"Analyzed {processed}/{total} media files",
                checkpoint_data={
                    "schema_version": 1,
                    "phase": "probing",
                    "root_keys": root_keys,
                    "last_indexed_path_id": last_indexed_path_id,
                    "processed": processed,
                    "probe_generation": probe_generation,
                },
            )

        context.checkpoint(
            progress_current=int(total),
            progress_total=int(total),
            progress_message="Media analysis completed",
            checkpoint_data={
                "schema_version": 1,
                "phase": "completed",
                "root_keys": root_keys,
                "last_indexed_path_id": last_indexed_path_id,
                "processed": int(total),
                "probe_generation": probe_generation,
            },
        )
