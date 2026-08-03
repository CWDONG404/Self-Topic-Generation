from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import DBSession, get_paper, get_practice_session
from app.models import PaperQuestion, PracticeAnswer, PracticeSession, Question
from app.schemas import (
    AnswerBatch,
    AnswerFeedback,
    AnswerSubmit,
    CitationRead,
    OptionRead,
    PracticeAnswerRead,
    PracticeQuestionRead,
    PracticeResult,
    PracticeSessionCreate,
    PracticeSessionDetail,
    PracticeSessionRead,
    PracticeSessionUpdate,
    QuestionRead,
    WrongAnswerRetryCreate,
)

router = APIRouter(prefix="/practice-sessions", tags=["练习与考试"])


def _load_questions(db: DBSession, question_ids: list[str]) -> list[Question]:
    if not question_ids:
        return []
    items = db.scalars(
        select(Question)
        .options(
            selectinload(Question.options),
            selectinload(Question.citations),
            selectinload(Question.reviews),
        )
        .where(Question.id.in_(question_ids))
    ).all()
    by_id = {item.id: item for item in items}
    return [by_id[item_id] for item_id in question_ids if item_id in by_id]


def _session_detail(db: DBSession, session: PracticeSession) -> PracticeSessionDetail:
    questions = _load_questions(db, session.assigned_question_ids)
    answers = db.scalars(
        select(PracticeAnswer)
        .where(PracticeAnswer.session_id == session.id)
        .order_by(PracticeAnswer.answered_at)
    ).all()
    reveal_correctness = session.mode != "exam" or session.status == "submitted"
    return PracticeSessionDetail(
        **PracticeSessionRead.model_validate(session).model_dump(),
        questions=[
            PracticeQuestionRead(
                id=question.id,
                stem=question.stem,
                knowledge_point=question.knowledge_point,
                difficulty=question.difficulty,
                options=[OptionRead.model_validate(option) for option in question.options],
                correct_option=question.correct_option if reveal_correctness else None,
                explanation=question.explanation if reveal_correctness else None,
                citations=(
                    [CitationRead.model_validate(item) for item in question.citations]
                    if reveal_correctness
                    else []
                ),
            )
            for question in questions
        ],
        answers=[
            PracticeAnswerRead(
                question_id=answer.question_id,
                selected_option=answer.selected_option,
                is_correct=answer.is_correct if reveal_correctness else None,
                answered_at=answer.answered_at,
            )
            for answer in answers
        ],
    )


def _save_answer(db: DBSession, session: PracticeSession, payload: AnswerSubmit) -> AnswerFeedback:
    if session.status != "in_progress":
        raise HTTPException(status_code=409, detail="本次练习已经提交，不能继续修改答案")
    if payload.question_id not in session.assigned_question_ids:
        raise HTTPException(status_code=422, detail="题目不属于本次练习")
    question = db.get(Question, payload.question_id)
    if question is None:
        raise HTTPException(status_code=404, detail="题目不存在")
    answer = db.scalar(
        select(PracticeAnswer).where(
            PracticeAnswer.session_id == session.id,
            PracticeAnswer.question_id == payload.question_id,
        )
    )
    is_correct = payload.selected_option == question.correct_option
    if answer is None:
        answer = PracticeAnswer(
            session_id=session.id,
            question_id=payload.question_id,
            selected_option=payload.selected_option,
            is_correct=is_correct,
        )
        db.add(answer)
    else:
        answer.selected_option = payload.selected_option
        answer.is_correct = is_correct
        answer.answered_at = datetime.now(UTC)
    db.commit()
    reveal = session.mode != "exam"
    return AnswerFeedback(
        question_id=question.id,
        selected_option=payload.selected_option,
        is_correct=is_correct if reveal else None,
        correct_option=question.correct_option if reveal else None,
        explanation=question.explanation if reveal else None,
    )


@router.get("", response_model=list[PracticeSessionRead])
def list_practice_sessions(
    db: DBSession,
    paper_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
) -> list[PracticeSession]:
    statement = select(PracticeSession).order_by(PracticeSession.created_at.desc()).limit(limit)
    if paper_id:
        statement = statement.where(PracticeSession.paper_id == paper_id)
    return list(db.scalars(statement).all())


@router.post("", response_model=PracticeSessionDetail, status_code=status.HTTP_201_CREATED)
def create_practice_session(
    payload: PracticeSessionCreate, db: DBSession
) -> PracticeSessionDetail:
    paper = get_paper(db, payload.paper_id)
    available_ids = list(
        db.scalars(
            select(PaperQuestion.question_id)
            .join(Question, Question.id == PaperQuestion.question_id)
            .where(PaperQuestion.paper_id == paper.id, Question.status == "approved")
            .order_by(PaperQuestion.position)
        ).all()
    )
    requested_ids = payload.question_ids or available_ids
    if not requested_ids:
        raise HTTPException(status_code=409, detail="试卷中没有可练习题目")
    has_duplicates = len(requested_ids) != len(set(requested_ids))
    if has_duplicates or not set(requested_ids).issubset(available_ids):
        raise HTTPException(status_code=422, detail="练习题目列表无效")
    session = PracticeSession(
        paper_id=paper.id,
        mode=payload.mode,
        assigned_question_ids=requested_ids,
        total_count=len(requested_ids),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return _session_detail(db, session)


@router.get("/wrong-answers")
def list_wrong_answers(db: DBSession) -> list[dict]:
    """按题目聚合历史错答，供错题本和一键重练使用。"""

    answers = db.scalars(
        select(PracticeAnswer)
        .join(PracticeSession, PracticeSession.id == PracticeAnswer.session_id)
        .options(
            selectinload(PracticeAnswer.session),
            selectinload(PracticeAnswer.question).selectinload(Question.options),
            selectinload(PracticeAnswer.question).selectinload(Question.citations),
            selectinload(PracticeAnswer.question).selectinload(Question.reviews),
        )
        .where(
            PracticeSession.status == "submitted",
            PracticeAnswer.is_correct.is_(False),
        )
        .order_by(PracticeAnswer.answered_at.desc())
    ).all()
    grouped: dict[str, dict] = {}
    for answer in answers:
        current = grouped.get(answer.question_id)
        if current is None:
            grouped[answer.question_id] = {
                "question": QuestionRead.model_validate(answer.question).model_dump(mode="json"),
                "selected_option": answer.selected_option,
                "wrong_count": 1,
                "last_answered_at": answer.answered_at,
                "paper_id": answer.session.paper_id,
            }
        else:
            current["wrong_count"] += 1
    return list(grouped.values())


@router.post(
    "/wrong-answers/retry",
    response_model=PracticeSessionDetail,
    status_code=status.HTTP_201_CREATED,
)
def retry_selected_wrong_answers(
    payload: WrongAnswerRetryCreate, db: DBSession
) -> PracticeSessionDetail:
    question_ids = list(dict.fromkeys(payload.question_ids))
    if len(question_ids) != len(payload.question_ids):
        raise HTTPException(status_code=422, detail="错题列表不能包含重复题目")
    historical_wrong_ids = set(
        db.scalars(
            select(PracticeAnswer.question_id)
            .join(PracticeSession, PracticeSession.id == PracticeAnswer.session_id)
            .where(
                PracticeSession.status == "submitted",
                PracticeAnswer.is_correct.is_(False),
                PracticeAnswer.question_id.in_(question_ids),
            )
        ).all()
    )
    if historical_wrong_ids != set(question_ids):
        raise HTTPException(status_code=422, detail="只能选择错题本中已有的题目重练")
    questions = _load_questions(db, question_ids)
    if len(questions) != len(question_ids):
        raise HTTPException(status_code=422, detail="部分错题不存在")
    paper_id = db.scalar(
        select(PaperQuestion.paper_id)
        .where(PaperQuestion.question_id == question_ids[0])
        .order_by(PaperQuestion.id)
    )
    if paper_id is None:
        raise HTTPException(status_code=409, detail="错题未关联可用试卷")
    retried = PracticeSession(
        paper_id=paper_id,
        mode="wrong_answers",
        assigned_question_ids=question_ids,
        total_count=len(question_ids),
    )
    db.add(retried)
    db.commit()
    db.refresh(retried)
    return _session_detail(db, retried)


@router.get("/{session_id}", response_model=PracticeSessionDetail)
def read_practice_session(session_id: str, db: DBSession) -> PracticeSessionDetail:
    return _session_detail(db, get_practice_session(db, session_id))


@router.patch("/{session_id}", response_model=PracticeSessionDetail)
def update_practice_session(
    session_id: str, payload: PracticeSessionUpdate, db: DBSession
) -> PracticeSessionDetail:
    session = get_practice_session(db, session_id)
    if payload.current_index >= session.total_count:
        raise HTTPException(status_code=422, detail="题目索引超出范围")
    session.current_index = payload.current_index
    db.commit()
    db.refresh(session)
    return _session_detail(db, session)


@router.get("/{session_id}/answers", response_model=list[PracticeAnswerRead])
def list_answers(session_id: str, db: DBSession) -> list[PracticeAnswerRead]:
    session = get_practice_session(db, session_id)
    return _session_detail(db, session).answers


@router.post("/{session_id}/answers", response_model=AnswerFeedback)
def submit_answer(
    session_id: str, payload: AnswerSubmit, db: DBSession
) -> AnswerFeedback:
    return _save_answer(db, get_practice_session(db, session_id), payload)


@router.patch("/{session_id}/answers", response_model=list[AnswerFeedback])
def submit_answer_batch(
    session_id: str, payload: AnswerBatch, db: DBSession
) -> list[AnswerFeedback]:
    session = get_practice_session(db, session_id)
    if len({item.question_id for item in payload.answers}) != len(payload.answers):
        raise HTTPException(status_code=422, detail="批量答案包含重复题目")
    return [_save_answer(db, session, item) for item in payload.answers]


@router.put("/{session_id}/answers/{question_id}", response_model=AnswerFeedback)
def put_answer(
    session_id: str,
    question_id: str,
    payload: AnswerSubmit,
    db: DBSession,
) -> AnswerFeedback:
    if payload.question_id != question_id:
        raise HTTPException(status_code=422, detail="路径与答案中的题目 ID 不一致")
    return _save_answer(db, get_practice_session(db, session_id), payload)


@router.post("/{session_id}/submit", response_model=PracticeResult)
def submit_practice(session_id: str, db: DBSession) -> PracticeResult:
    session = get_practice_session(db, session_id)
    if session.status != "submitted":
        answers = db.scalars(
            select(PracticeAnswer).where(PracticeAnswer.session_id == session.id)
        ).all()
        session.correct_count = sum(answer.is_correct for answer in answers)
        session.score = round(session.correct_count / session.total_count * 100, 2)
        session.status = "submitted"
        session.submitted_at = datetime.now(UTC)
        db.commit()
        db.refresh(session)
    return _practice_result(db, session)


def _practice_result(db: DBSession, session: PracticeSession) -> PracticeResult:
    questions = _load_questions(db, session.assigned_question_ids)
    answers = db.scalars(
        select(PracticeAnswer)
        .where(PracticeAnswer.session_id == session.id)
        .order_by(PracticeAnswer.answered_at)
    ).all()
    return PracticeResult(
        **PracticeSessionRead.model_validate(session).model_dump(),
        answers=[PracticeAnswerRead.model_validate(answer) for answer in answers],
        questions=[QuestionRead.model_validate(question) for question in questions],
    )


@router.get("/{session_id}/result", response_model=PracticeResult)
def read_result(session_id: str, db: DBSession) -> PracticeResult:
    session = get_practice_session(db, session_id)
    if session.status != "submitted":
        raise HTTPException(status_code=409, detail="练习尚未提交")
    return _practice_result(db, session)


@router.post(
    "/{session_id}/retry-mistakes",
    response_model=PracticeSessionDetail,
    status_code=status.HTTP_201_CREATED,
)
def retry_mistakes(session_id: str, db: DBSession) -> PracticeSessionDetail:
    session = get_practice_session(db, session_id)
    if session.status != "submitted":
        raise HTTPException(status_code=409, detail="请先提交当前练习")
    correct_ids = set(
        db.scalars(
            select(PracticeAnswer.question_id).where(
                PracticeAnswer.session_id == session.id,
                PracticeAnswer.is_correct.is_(True),
            )
        ).all()
    )
    mistake_ids = [item for item in session.assigned_question_ids if item not in correct_ids]
    if not mistake_ids:
        raise HTTPException(status_code=409, detail="本次练习没有错题")
    retried = PracticeSession(
        paper_id=session.paper_id,
        mode="practice",
        assigned_question_ids=mistake_ids,
        total_count=len(mistake_ids),
    )
    db.add(retried)
    db.commit()
    db.refresh(retried)
    return _session_detail(db, retried)
