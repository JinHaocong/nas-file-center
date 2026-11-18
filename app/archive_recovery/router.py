"""Authenticated archive recovery endpoints; archive contents remain local."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import stat
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.archive_recovery.core import RecoveryError, detect_format
from app.archive_recovery.integration import (
    tmpfs_available, report_path, store_one_time_password, discard_one_time_password,
)
from app.auth.dependencies import require_admin_user
from app.models import WorkJob
from app.path_safety import require_allowed_path, require_unreserved_path

router = APIRouter(prefix='/api/archive-recovery', tags=['archive-recovery'],
                   dependencies=[Depends(require_admin_user)])


class RecoveryRequest(BaseModel):
    source: str = Field(min_length=1, max_length=4096)
    password: str | None = None
    deep: bool = True


def qualified_source(request: Request, raw: str) -> Path:
    """Do not accept symlink input or any read outside authoritative roots."""
    settings = request.app.state.settings
    original = Path(raw)
    if original.is_symlink():
        raise HTTPException(422, 'SOURCE_SYMLINK_REJECTED')
    try:
        source = require_unreserved_path(
            require_allowed_path(raw, settings.allowed_roots), settings.quarantine_root)
        if not source.is_file() or not stat.S_ISREG(source.stat().st_mode):
            raise HTTPException(422, 'SOURCE_NOT_REGULAR_FILE')
        return source
    except (OSError, ValueError) as exc:
        raise HTTPException(422, 'SOURCE_NOT_ALLOWED') from exc


@router.post('/check')
def check_archive(request: Request, payload: RecoveryRequest):
    """Read-only format/space/dependency preflight (no arbitrary extraction)."""
    source = qualified_source(request, payload.source)
    try:
        fmt = detect_format(source)
    except RecoveryError as exc:
        raise HTTPException(422, str(exc)) from exc
    free = shutil.disk_usage(source.parent).free
    import ctypes.util
    return {'format': fmt, 'source': str(source), 'free_bytes': free,
            'source_bytes': source.stat().st_size,
            # The API is allowed to enqueue; the Worker validates actual parent
            # write access immediately before exclusive output-directory creation.
            'mutation_enabled': request.app.state.settings.allow_mutation,
            'worker_write_check_required': True,
            'dependency_available': fmt in ('tar', 'zip') or bool(ctypes.util.find_library('archive')),
            # Read-only API-side RAM channel check; Worker must share the mount.
            'password_channel_available': tmpfs_available(),
            'deep_strategy': 'tar_rescan' if fmt == 'tar' else
                             'zip_local_headers' if fmt == 'zip' else
                             'aes_lzma2_crc_reset_when_supported' if fmt == '7z' else
                             'nested_tar_only',
            'warning': 'Unknown required space; extraction stops at configured resource caps.'}


@router.post('/start', status_code=202)
def start_archive(request: Request, payload: RecoveryRequest):
    """Freeze intent and enqueue; only the Worker creates the sibling output directory."""
    source = qualified_source(request, payload.source)
    settings = request.app.state.settings
    if not settings.allow_mutation:
        raise HTTPException(403, 'MUTATION_DISABLED')
    try:
        detect_format(source)
    except RecoveryError as exc:
        raise HTTPException(422, str(exc)) from exc
    if payload.password and len(payload.password.encode('utf-8')) > 4096:
        raise HTTPException(422, 'PASSWORD_TOO_LONG')
    if payload.password and not tmpfs_available():
        raise HTTPException(503, 'PASSWORD_CHANNEL_UNAVAILABLE: configure shared tmpfs')

    # Freeze source and parent identities. The API performs no media-root writes.
    source_stat = os.stat(source, follow_symlinks=False)
    parent_stat = os.stat(source.parent, follow_symlinks=False)
    if not stat.S_ISREG(source_stat.st_mode) or not stat.S_ISDIR(parent_stat.st_mode):
        raise HTTPException(409, 'SOURCE_OR_PARENT_CHANGED')
    output = None
    token = None
    try:
        for _ in range(10):
            candidate = source.parent / (source.name[:60] + '_恢复结果_' + uuid4().hex[:8])
            # Read-only collision observation only. Worker still uses exclusive mkdir.
            if not os.path.lexists(candidate):
                output = candidate
                break
        if output is None:
            raise HTTPException(409, 'OUTPUT_CONFLICT')

        if payload.password:
            token = uuid4().hex
            try:
                store_one_time_password(token, payload.password)
            except (RecoveryError, OSError) as exc:
                raise HTTPException(503, 'PASSWORD_CHANNEL_UNAVAILABLE') from exc
        with request.app.state.service.SessionLocal() as session:
            job = WorkJob(kind='archive-recovery', status='queued',
                          state_json=json.dumps({
                              'source': str(source), 'output': str(output),
                              'identity': [str(source_stat.st_dev), str(source_stat.st_ino),
                                           str(source_stat.st_size), str(source_stat.st_mtime_ns)],
                              'parent_identity': [str(parent_stat.st_dev), str(parent_stat.st_ino)],
                              'secret_token': token, 'deep': payload.deep,
                          }, ensure_ascii=False))
            session.add(job)
            session.commit()
            result_id = job.id
        return {'work_job_id': result_id, 'status': 'queued', 'output': str(output)}
    except BaseException:
        discard_one_time_password(token)
        raise


@router.get('/{job_id}/report')
def get_recovery_report(request: Request, job_id: int):
    """Reports are metadata under /config; no arbitrary path accepts input."""
    with request.app.state.service.SessionLocal() as session:
        job = session.get(WorkJob, job_id)
        if not job or job.kind != 'archive-recovery':
            raise HTTPException(404, 'Recovery task not found')
    try:
        with report_path(request.app.state.settings, job_id).open('r', encoding='utf-8') as handle:
            return json.load(handle)
    except FileNotFoundError as exc:
        raise HTTPException(404, 'Report not ready') from exc