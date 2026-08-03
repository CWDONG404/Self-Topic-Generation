from __future__ import annotations

import asyncio
import ipaddress
import json
import secrets
from datetime import UTC, datetime
from urllib.parse import urlparse

from fastapi import APIRouter, Header, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import DBSession, get_job, get_library
from app.core.config import settings
from app.core.job_events import append_job_event
from app.core.queue import enqueue_task
from app.db import SessionLocal
from app.models import Document, GenerationJob, JobEvent, ModelProfile
from app.schemas import JobCreate, JobEventRead, JobRead

router = APIRouter(prefix="/jobs", tags=["出题任务"])
TERMINAL_STATUSES = {"completed", "partial", "failed", "canceled"}
REQUIRED_MODEL_ROLES = ("blueprint", "author", "reviewer")
MODEL_ROLE_ALIASES = {
    "blueprint": ("blueprint", "outline", "planner"),
    "author": ("author", "generator", "question", "question_author"),
    "reviewer": ("reviewer", "review", "validator", "question_reviewer"),
    "vision": ("vision", "visual", "multimodal"),
    "embedding": ("embedding", "embeddings", "retrieval"),
}
MODEL_ROLE_BY_ALIAS = {
    alias: role for role, aliases in MODEL_ROLE_ALIASES.items() for alias in aliases
}
MODEL_ROLE_CAPABILITIES = {
    "blueprint": "structured_output",
    "author": "structured_output",
    "reviewer": "structured_output",
    "vision": "vision",
    "embedding": "embedding",
}
QUEUE_ERROR = "任务入队失败，请检查任务队列配置或服务状态后重试"


def _is_local_model_endpoint(base_url: str) -> bool:
    host = (urlparse(base_url).hostname or "").casefold()
    if host in {"localhost", "host.docker.internal", "ollama", "::1"}:
        return True
    if host.endswith(".local"):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_loopback or address.is_private or address.is_link_local


def _validate_documents(payload: JobCreate, db: DBSession) -> None:
    requested_ids = set(payload.outline_document_ids)
    requested_ids.update(item.document_id for item in payload.source_documents)
    documents = {
        item.id: item
        for item in db.scalars(
            select(Document)
            .options(selectinload(Document.versions))
            .where(Document.id.in_(requested_ids), Document.archived.is_(False))
        ).all()
    }
    missing = requested_ids - set(documents)
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"文档不存在或已归档：{', '.join(sorted(missing))}",
        )
    for document in documents.values():
        if document.library_id != payload.library_id:
            raise HTTPException(status_code=422, detail="所有文档必须属于所选资料库")
        latest = max(document.versions, key=lambda item: item.version_number, default=None)
        if latest is None or latest.status != "ready":
            raise HTTPException(status_code=409, detail=f"文档“{document.name}”尚未解析完成")
    for allocation in payload.source_documents:
        document = documents[allocation.document_id]
        outline_allowed = (
            payload.allow_outline_as_evidence
            and document.role == "outline"
            and document.allow_as_evidence
        )
        if document.role != "source" and not outline_allowed:
            raise HTTPException(
                status_code=422,
                detail="正文配额只能选择正文资料，或已明确允许作为证据的重点资料",
            )


def _resolve_model_assignments(
    model_assignments: dict[str, str],
    execution_mode: str,
    db: DBSession,
) -> dict[str, str]:
    if settings.strict_local_mode and execution_mode != "local":
        raise HTTPException(status_code=422, detail="部署已启用 STRICT_LOCAL_MODE，只允许本地任务")

    assignments: dict[str, str] = {}
    unknown_roles: list[str] = []
    for alias, profile_id in model_assignments.items():
        role = MODEL_ROLE_BY_ALIAS.get(alias)
        if role is None:
            unknown_roles.append(alias)
            continue
        existing = assignments.get(role)
        if existing is not None and existing != profile_id:
            raise HTTPException(
                status_code=422,
                detail=f"角色 {role} 通过多个别名选择了不同模型",
            )
        assignments[role] = profile_id
    if unknown_roles:
        raise HTTPException(
            status_code=422,
            detail=f"不支持的模型角色：{', '.join(sorted(unknown_roles))}",
        )

    enabled_profiles = list(
        db.scalars(
            select(ModelProfile)
            .where(ModelProfile.enabled.is_(True))
            .order_by(ModelProfile.created_at, ModelProfile.id)
        ).all()
    )
    profiles = {profile.id: profile for profile in enabled_profiles}
    explicit_ids = set(assignments.values())
    if not explicit_ids.issubset(profiles):
        raise HTTPException(status_code=422, detail="模型角色配置不存在或已停用")

    for role in MODEL_ROLE_ALIASES:
        if role in assignments:
            continue
        role_defaults = [
            profile
            for profile in enabled_profiles
            if role in (profile.default_roles or [])
        ]
        if len(role_defaults) > 1:
            raise HTTPException(
                status_code=422,
                detail=f"角色 {role} 配置了多个默认模型，请保留一个",
            )
        if role_defaults:
            assignments[role] = role_defaults[0].id

    global_defaults = [profile for profile in enabled_profiles if profile.is_default]
    if len(global_defaults) > 1:
        raise HTTPException(status_code=422, detail="配置了多个全局默认模型，请保留一个")

    for role in REQUIRED_MODEL_ROLES:
        if role in assignments:
            continue
        if global_defaults:
            assignments[role] = global_defaults[0].id
            continue
        capability = MODEL_ROLE_CAPABILITIES[role]
        compatible = [
            profile
            for profile in enabled_profiles
            if (profile.capabilities or {}).get(capability, False)
        ]
        if len(compatible) == 1:
            assignments[role] = compatible[0].id
            continue
        if not compatible:
            raise HTTPException(
                status_code=422,
                detail=f"缺少角色 {role} 的可用模型（需要 {capability} 能力）",
            )
        raise HTTPException(
            status_code=422,
            detail=f"角色 {role} 有多个可用模型，请显式选择或配置 default_roles",
        )

    for role, profile_id in assignments.items():
        profile = profiles[profile_id]
        capability = MODEL_ROLE_CAPABILITIES[role]
        if not (profile.capabilities or {}).get(capability, False):
            raise HTTPException(
                status_code=422,
                detail=f"角色 {role} 所选模型未声明 {capability} 能力",
            )
        if execution_mode == "local" and not _is_local_model_endpoint(profile.base_url):
            raise HTTPException(
                status_code=422,
                detail=(
                    "本地模式只能使用本机、局域网或 Docker 内的模型地址，"
                    "禁止自动回退云端"
                ),
            )
    return assignments


def _validate_models(payload: JobCreate, db: DBSession) -> dict[str, str]:
    return _resolve_model_assignments(
        payload.model_assignments,
        payload.execution_mode,
        db,
    )


def _mark_enqueue_failed(db: DBSession, job: GenerationJob) -> None:
    job.error = QUEUE_ERROR
    job.completed_at = datetime.now(UTC)
    append_job_event(
        db,
        job.id,
        stage="failed",
        progress=100,
        message=QUEUE_ERROR,
        status="failed",
    )


@router.get("", response_model=list[JobRead])
def list_jobs(
    db: DBSession,
    library_id: str | None = Query(None),
    job_status: str | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
) -> list[GenerationJob]:
    statement = select(GenerationJob).order_by(GenerationJob.created_at.desc()).limit(limit)
    if library_id:
        statement = statement.where(GenerationJob.library_id == library_id)
    if job_status:
        statement = statement.where(GenerationJob.status == job_status)
    return list(db.scalars(statement).all())


@router.post("", response_model=JobRead, status_code=status.HTTP_201_CREATED)
def create_job(payload: JobCreate, db: DBSession) -> GenerationJob:
    get_library(db, payload.library_id)
    _validate_documents(payload, db)
    resolved_assignments = _validate_models(payload, db)
    # PostgreSQL INTEGER 是有符号 32 位；31 位随机值可直接持久化并保持充足随机性。
    seed = payload.random_seed if payload.random_seed is not None else secrets.randbits(31)
    request_json = payload.model_dump(mode="json")
    request_json["random_seed"] = seed
    request_json["model_assignments"] = resolved_assignments
    job = GenerationJob(
        library_id=payload.library_id,
        status="queued",
        stage="queued",
        progress=0.0,
        request_json=request_json,
        target_count=payload.target_count,
        random_seed=seed,
        prompt_version="v2-quality",
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    append_job_event(
        db,
        job.id,
        stage="queued",
        progress=0,
        message="出题任务已进入队列",
        payload={"target_count": payload.target_count},
    )
    if not enqueue_task("generate_exam", job.id):
        _mark_enqueue_failed(db, job)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=QUEUE_ERROR,
        )
    db.refresh(job)
    return job


@router.get("/{job_id}", response_model=JobRead)
def read_job(job_id: str, db: DBSession) -> GenerationJob:
    return get_job(db, job_id)


@router.get("/{job_id}/cancel")
def read_cancel_status(job_id: str, db: DBSession) -> dict[str, bool | str]:
    job = get_job(db, job_id)
    return {"id": job.id, "status": job.status, "cancel_requested": job.cancel_requested}


@router.post("/{job_id}/cancel", response_model=JobRead)
def cancel_job(job_id: str, db: DBSession) -> GenerationJob:
    job = get_job(db, job_id)
    if job.status in TERMINAL_STATUSES:
        return job
    job.cancel_requested = True
    now = datetime.now(UTC)
    if job.status == "queued":
        job.status = "canceled"
        job.completed_at = now
        stage = "canceled"
        message = "任务已取消"
    else:
        job.status = "cancel_requested"
        stage = job.stage
        message = "已请求取消，正在等待当前步骤安全停止"
    db.commit()
    append_job_event(
        db,
        job.id,
        stage=stage,
        progress=job.progress,
        message=message,
        status=job.status,
    )
    db.refresh(job)
    return job


@router.post("/{job_id}/retry", response_model=JobRead, status_code=status.HTTP_201_CREATED)
def retry_job(job_id: str, db: DBSession) -> GenerationJob:
    original = get_job(db, job_id)
    if original.status not in {"failed", "canceled", "partial"}:
        raise HTTPException(status_code=409, detail="只有失败、取消或部分完成的任务可以重试")
    request_json = dict(original.request_json or {})
    request_json["model_assignments"] = _resolve_model_assignments(
        dict(request_json.get("model_assignments") or {}),
        str(request_json.get("execution_mode") or "local"),
        db,
    )
    retried = GenerationJob(
        library_id=original.library_id,
        parent_job_id=original.id,
        status="queued",
        stage="queued",
        progress=0,
        request_json=request_json,
        target_count=original.target_count,
        random_seed=original.random_seed,
        prompt_version=original.prompt_version,
    )
    db.add(retried)
    db.commit()
    db.refresh(retried)
    append_job_event(
        db,
        retried.id,
        stage="queued",
        progress=0,
        message="重试任务已进入队列",
        payload={"parent_job_id": original.id},
    )
    if not enqueue_task("generate_exam", retried.id):
        _mark_enqueue_failed(db, retried)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=QUEUE_ERROR,
        )
    db.refresh(retried)
    return retried


@router.get("/{job_id}/events")
async def stream_job_events(
    job_id: str,
    request: Request,
    after: int = Query(0, ge=0),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
) -> StreamingResponse:
    try:
        cursor = max(after, int(last_event_id or 0))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Last-Event-ID 必须是整数") from exc
    with SessionLocal() as db:
        if db.get(GenerationJob, job_id) is None:
            raise HTTPException(status_code=404, detail="任务不存在")

    async def event_stream():  # type: ignore[no-untyped-def]
        nonlocal cursor
        idle_rounds = 0
        while True:
            if await request.is_disconnected():
                return
            with SessionLocal() as db:
                events = db.scalars(
                    select(JobEvent)
                    .where(JobEvent.job_id == job_id, JobEvent.sequence > cursor)
                    .order_by(JobEvent.sequence)
                    .limit(200)
                ).all()
                job = db.get(GenerationJob, job_id)
                terminal = job is None or job.status in TERMINAL_STATUSES
            if events:
                idle_rounds = 0
                for event in events:
                    cursor = event.sequence
                    data = JobEventRead.model_validate(event).model_dump(mode="json")
                    serialized = json.dumps(data, ensure_ascii=False)
                    yield f"id: {event.sequence}\nevent: progress\ndata: {serialized}\n\n"
            else:
                idle_rounds += 1
                if idle_rounds >= 30:
                    idle_rounds = 0
                    yield ": keep-alive\n\n"
            if terminal and not events:
                return
            await asyncio.sleep(settings.sse_poll_interval_seconds)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
