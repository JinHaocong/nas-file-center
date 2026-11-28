"""Administrator-only entry point for cloud-to-NAS transfers."""
from __future__ import annotations

import json
import os
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, text

from app.auth.dependencies import require_admin_user
from app.models import WorkJob
from .handler import (
    CloudCopyError, JOB_KIND, STAGE_PREFIX, active_source, configured_deployment,
    directory_identity, open_destination_parent, remote_directory, require_new_folder,
)


router = APIRouter(prefix="/api/cloud-copy", tags=["cloud-copy"], dependencies=[Depends(require_admin_user)])


class NewCloudCopy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: str = Field(min_length=1, max_length=19)
    remote_root: str = Field(min_length=1, max_length=4096)
    local_parent: str = Field(min_length=1, max_length=4096)
    folder_name: str = Field(min_length=1, max_length=255)


@router.get("/configuration")
def configuration(request: Request):
    deployment = configured_deployment(request.app.state.settings)
    if deployment:
        with request.app.state.service.SessionLocal() as session:
            if active_source(session, deployment.source_id):
                return {"configured": True, "source_id": deployment.source_id,
                        "local_root": str(deployment.local_root)}
    return {"configured": False, "source_id": None, "local_root": None}


@router.post("", status_code=202)
def start_copy(request: Request, payload: NewCloudCopy):
    settings = request.app.state.settings
    if not settings.allow_mutation:
        raise HTTPException(403, "当前部署为只读模式，无法复制文件到 NAS。")
    deployment = configured_deployment(settings)
    if deployment is None:
        raise HTTPException(503, "云端复制尚未完成部署配置。")
    if payload.source_id != deployment.source_id:
        raise HTTPException(422, "请选择部署配置中绑定的 OpenList 来源。")
    try:
        remote = "/".join(remote_directory(payload.remote_root))
    except ValueError:
        raise HTTPException(422, "请选择有效的云端子目录。") from None
    try:
        with open_destination_parent(deployment, settings, payload.local_parent, payload.folder_name) as (parent, fd):
            require_new_folder(fd, payload.folder_name)
            binding = directory_identity(os.fstat(fd))
    except CloudCopyError as exc:
        raise HTTPException(409, str(exc)) from None
    except (OSError, RuntimeError, ValueError):
        raise HTTPException(422, "请选择导入根目录内的实际文件夹，并填写有效的新目录名称。") from None

    destination = str(parent / payload.folder_name)
    staging = str(parent / (STAGE_PREFIX + uuid4().hex))
    with request.app.state.service.SessionLocal() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        source = active_source(session, deployment.source_id)
        if source is None:
            raise HTTPException(422, "OpenList 来源已停用。")
        pending = session.scalar(select(WorkJob.id).where(
            WorkJob.kind == JOB_KIND,
            WorkJob.status.in_(("queued", "running", "paused", "cancel_requested")),
            func.json_extract(WorkJob.state_json, "$.local_root") == destination,
        ).limit(1))
        if pending is not None:
            raise HTTPException(409, "这个目标已有复制任务。")
        state = {
            "schema_version": 1, "deployment": deployment.fingerprint(),
            "source_id": deployment.source_id, "source_revision": source.revision,
            "remote_root": remote, "local_root": destination, "staging_path": staging,
            "parent_identity": binding,
        }
        job = WorkJob(kind=JOB_KIND, status="queued", progress_message="等待 Worker 开始云端复制",
                      state_json=json.dumps(state, ensure_ascii=False))
        session.add(job)
        session.flush()
        result = {"job_id": str(job.id), "status": job.status}
        session.commit()
    return result
