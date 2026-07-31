from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import GenerationJob, JobEvent


def append_job_event(
    db: Session,
    job_id: str,
    *,
    stage: str,
    progress: float,
    message: str = "",
    payload: dict[str, Any] | None = None,
    status: str | None = None,
    commit: bool = True,
) -> JobEvent:
    """以数据库为权威源追加单调任务事件。

    PostgreSQL 上锁定任务行以避免多个 worker 产生相同 sequence；SQLite 测试环境
    由事务串行执行。
    """

    job = db.scalar(
        select(GenerationJob).where(GenerationJob.id == job_id).with_for_update()
    )
    if job is None:
        raise LookupError(f"任务不存在：{job_id}")

    normalized_progress = max(job.progress, min(100.0, max(0.0, float(progress))))
    sequence = (
        db.scalar(
            select(func.coalesce(func.max(JobEvent.sequence), 0)).where(
                JobEvent.job_id == job_id
            )
        )
        or 0
    ) + 1
    event = JobEvent(
        job_id=job_id,
        sequence=sequence,
        stage=stage,
        progress=normalized_progress,
        message=message,
        payload=payload or {},
    )
    job.stage = stage
    job.progress = normalized_progress
    if status:
        job.status = status
    db.add(event)
    if commit:
        db.commit()
        db.refresh(event)
    else:
        db.flush()
    return event
