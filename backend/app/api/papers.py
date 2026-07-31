from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.api.deps import DBSession, get_paper, get_question
from app.core.queue import enqueue_task
from app.core.text import question_hash
from app.models import Citation, Paper, PaperQuestion, Question, QuestionOption, QuestionReview
from app.schemas import PaperDetail, PaperRead, QuestionRead, QuestionUpdate

router = APIRouter(tags=["试卷与题目"])
QUEUE_ERROR = "任务入队失败，请检查任务队列配置或服务状态后重试"


def _question_statement():  # type: ignore[no-untyped-def]
    return select(Question).options(
        selectinload(Question.options),
        selectinload(Question.citations),
        selectinload(Question.reviews),
    )


def _paper_detail(db: DBSession, paper: Paper) -> PaperDetail:
    links = db.scalars(
        select(PaperQuestion)
        .options(
            selectinload(PaperQuestion.question).selectinload(Question.options),
            selectinload(PaperQuestion.question).selectinload(Question.citations),
            selectinload(PaperQuestion.question).selectinload(Question.reviews),
        )
        .where(PaperQuestion.paper_id == paper.id)
        .order_by(PaperQuestion.position)
    ).all()
    return PaperDetail(
        **PaperRead.model_validate(paper).model_dump(),
        questions=[QuestionRead.model_validate(link.question) for link in links],
    )


@router.get("/papers", response_model=list[PaperRead])
def list_papers(
    db: DBSession,
    library_id: str | None = Query(None),
    paper_status: str | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
) -> list[Paper]:
    statement = select(Paper).order_by(Paper.created_at.desc()).limit(limit)
    if library_id:
        statement = statement.where(Paper.library_id == library_id)
    if paper_status:
        statement = statement.where(Paper.status == paper_status)
    return list(db.scalars(statement).all())


@router.get("/papers/{paper_id}", response_model=PaperDetail)
def read_paper(paper_id: str, db: DBSession) -> PaperDetail:
    return _paper_detail(db, get_paper(db, paper_id))


@router.get("/questions/{question_id}", response_model=QuestionRead)
def read_question(question_id: str, db: DBSession) -> QuestionRead:
    question = db.scalar(_question_statement().where(Question.id == question_id))
    if question is None:
        raise HTTPException(status_code=404, detail="题目不存在")
    return QuestionRead.model_validate(question)


@router.patch("/questions/{question_id}", response_model=QuestionRead)
def update_question(
    question_id: str, payload: QuestionUpdate, db: DBSession
) -> QuestionRead:
    question = db.scalar(_question_statement().where(Question.id == question_id))
    if question is None:
        raise HTTPException(status_code=404, detail="题目不存在")
    values = payload.model_dump(exclude_unset=True, exclude={"options"})
    for key, value in values.items():
        setattr(question, key, value.strip() if isinstance(value, str) else value)
    if payload.stem is not None:
        question.normalized_hash = question_hash(payload.stem)
    if payload.options is not None:
        existing = {option.label: option for option in question.options}
        for position, label in enumerate(("A", "B", "C", "D")):
            if label in existing:
                existing[label].text = payload.options[label].strip()
                existing[label].position = position
            else:
                question.options.append(
                    QuestionOption(
                        label=label,
                        text=payload.options[label].strip(),
                        position=position,
                    )
                )
    question.status = "edited"
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="题干与资料库中已有题目完全重复") from exc
    question = db.scalar(_question_statement().where(Question.id == question_id))
    assert question is not None
    return QuestionRead.model_validate(question)


@router.post("/questions/{question_id}/disable", response_model=QuestionRead)
def disable_question(question_id: str, db: DBSession) -> QuestionRead:
    question = get_question(db, question_id)
    question.status = "disabled"
    db.commit()
    loaded = db.scalar(_question_statement().where(Question.id == question_id))
    assert loaded is not None
    return QuestionRead.model_validate(loaded)


@router.post("/questions/{question_id}/review", response_model=QuestionRead)
def review_question(question_id: str, db: DBSession) -> QuestionRead:
    question = get_question(db, question_id)
    previous_status = question.status
    question.status = "review_pending"
    review = QuestionReview(
        question_id=question.id,
        status="pending",
        issues=[],
        rationale="已请求重新审查",
    )
    db.add(review)
    db.commit()
    if not enqueue_task("review_question", question.id):
        question.status = previous_status
        review.status = "failed"
        review.issues = [QUEUE_ERROR]
        review.rationale = "重新审查请求未能进入任务队列"
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=QUEUE_ERROR,
        )
    loaded = db.scalar(_question_statement().where(Question.id == question_id))
    assert loaded is not None
    return QuestionRead.model_validate(loaded)


@router.post("/questions/{question_id}/regenerate", response_model=QuestionRead)
def regenerate_question(question_id: str, db: DBSession) -> QuestionRead:
    question = get_question(db, question_id)
    if not question.citations:
        raise HTTPException(status_code=409, detail="该题没有可用于重新生成的证据引用")
    previous_status = question.status
    question.status = "regeneration_pending"
    db.commit()
    if not enqueue_task("regenerate_question", question.id):
        question.status = previous_status
        db.add(
            QuestionReview(
                question_id=question.id,
                status="failed",
                issues=[QUEUE_ERROR],
                rationale="重新生成请求未能进入任务队列，原题保持不变",
            )
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=QUEUE_ERROR,
        )
    loaded = db.scalar(_question_statement().where(Question.id == question_id))
    assert loaded is not None
    return QuestionRead.model_validate(loaded)


@router.get("/citations/{citation_id}")
def read_citation_anchor(citation_id: str, db: DBSession) -> dict:
    citation = db.get(Citation, citation_id)
    if citation is None:
        raise HTTPException(status_code=404, detail="引用不存在")
    return {
        "id": citation.id,
        "question_id": citation.question_id,
        "document_id": citation.document_id,
        "document_name": citation.document_name,
        "document_type": citation.document_type,
        "document_version_id": citation.document_version_id,
        "chunk_id": citation.chunk_id,
        "block_id": citation.block_id,
        "page_number": citation.page_number,
        "rects": citation.rects,
        "rectangles": citation.rectangles,
        "excerpt": citation.excerpt,
        "excerpt_hash": citation.excerpt_hash,
        "char_start": citation.char_start,
        "char_end": citation.char_end,
    }
