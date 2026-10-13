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
from app.archive_recovery.integration import SECRET_DIR, tmpfs_available, report_path
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
            'can_write': request.app.state.settings.allow_mutation and os.access(source.parent, os.W_OK),
            'dependency_available': fmt in ('tar', 'zip') or bool(ctypes.util.find_library('archive')),
            'deep_strategy': 'tar_rescan' if fmt == 'tar' else
                             'zip_local_headers' if fmt == 'zip' else
                             'aes_lzma2_crc_reset_when_supported' if fmt == '7z' else
                             'nested_tar_only',
            'warning': 'Unknown required space; extraction stops at configured resource caps.'}


@router.post('/start', status_code=202)
def start_archive(request: Request, payload: RecoveryRequest):
    """Create an exclusive sibling output directory and enqueue one Worker job."""
    source = qualified_source(request, payload.source)
    settings = request.app.state.settings
    if not settings.allow_mutation:
        raise HTTPException(403, 'MUTATION_DISABLED')
    if not os.access(source.parent, os.W_OK):
        raise HTTPException(422, 'SOURCE_PARENT_NOT_WRITABLE')
    try:
        detect_format(source)
    except RecoveryError as exc:
        raise HTTPException(422, str(exc)) from exc
    if payload.password and len(payload.password.encode('utf-8')) > 4096:
        raise HTTPException(422, 'PASSWORD_TOO_LONG')
    if payload.password and not tmpfs_available():
        raise HTTPException(503, 'PASSWORD_CHANNEL_UNAVAILABLE: configure shared tmpfs')
    # Explicit source identity and unique output directory; no overwrite.
    st = source.stat()
    output = None
    token = None
    try:
        for _ in range(10):
            candidate = source.parent / (source.name[:60] + '_恢复结果_' + uuid4().hex[:8])
            try:
                candidate.mkdir(mode=0o700)
                output = candidate
                break
            except FileExistsError:
                continue
        if output is None:
            raise HTTPException(409, 'OUTPUT_CONFLICT')
        output_stat = output.stat()
        if payload.password:
            token = uuid4().hex
            secret_path = SECRET_DIR / token
            secret_fd = os.open(secret_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(secret_fd, 'wb') as secret:
                secret.write(payload.password.encode('utf-8'))
                secret.flush()
        with request.app.state.service.SessionLocal() as session:
            job = WorkJob(kind='archive-recovery', status='queued',
                          state_json=json.dumps({
                              'source': str(source), 'output': str(output),
                              'identity': [str(st.st_dev), str(st.st_ino), str(st.st_size), str(st.st_mtime_ns)],
                              'secret_token': token, 'deep': payload.deep,
                              'output_identity': [str(output_stat.st_dev), str(output_stat.st_ino)],
                          }, ensure_ascii=False))
            session.add(job)
            session.commit()
            result_id = job.id
        return {'work_job_id': result_id, 'status': 'queued', 'output': str(output)}
    except BaseException:
        if token:
            (SECRET_DIR / token).unlink(missing_ok=True)
        if output:
            output.rmdir()  # Only the empty directory just registered by us.
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