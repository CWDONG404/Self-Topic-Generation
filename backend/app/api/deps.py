from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import (
    Document,
    GenerationJob,
    Library,
    ModelProfile,
    Paper,
    PracticeSession,
    Question,
)

DBSession = Annotated[Session, Depends(get_db)]


def get_or_404(db: Session, model, object_id: str, label: str):  # type: ignore[no-untyped-def]
    value = db.get(model, object_id)
    if value is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{label}不存在")
    return value


def get_library(db: Session, library_id: str) -> Library:
    return get_or_404(db, Library, library_id, "资料库")


def get_document(db: Session, document_id: str) -> Document:
    return get_or_404(db, Document, document_id, "文档")


def get_job(db: Session, job_id: str) -> GenerationJob:
    return get_or_404(db, GenerationJob, job_id, "任务")


def get_paper(db: Session, paper_id: str) -> Paper:
    return get_or_404(db, Paper, paper_id, "试卷")


def get_question(db: Session, question_id: str) -> Question:
    return get_or_404(db, Question, question_id, "题目")


def get_practice_session(db: Session, session_id: str) -> PracticeSession:
    return get_or_404(db, PracticeSession, session_id, "练习记录")


def get_model_profile(db: Session, profile_id: str) -> ModelProfile:
    return get_or_404(db, ModelProfile, profile_id, "模型配置")
