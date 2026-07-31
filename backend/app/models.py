from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from app.db import Base


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


class VectorType(TypeDecorator[list[float]]):
    """PostgreSQL 使用 pgvector，SQLite 测试环境退化为 JSON。"""

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):  # type: ignore[no-untyped-def]
        if dialect.name == "postgresql":
            from pgvector.sqlalchemy import Vector

            return dialect.type_descriptor(Vector())
        return dialect.type_descriptor(JSON())


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Library(TimestampMixin, Base):
    __tablename__ = "libraries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    documents: Mapped[list[Document]] = relationship(back_populates="library")
    jobs: Mapped[list[GenerationJob]] = relationship(back_populates="library")
    papers: Mapped[list[Paper]] = relationship(back_populates="library")


class Document(TimestampMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint(
            "role <> 'source' OR allow_as_evidence",
            name="ck_documents_source_evidence",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    library_id: Mapped[str] = mapped_column(
        ForeignKey("libraries.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    role: Mapped[str] = mapped_column(String(30), default="source", index=True)
    allow_as_evidence: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    extension: Mapped[str] = mapped_column(String(20), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(150), nullable=False)
    archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    library: Mapped[Library] = relationship(back_populates="documents")
    versions: Mapped[list[DocumentVersion]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="DocumentVersion.version_number",
    )


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    __table_args__ = (UniqueConstraint("document_id", "version_number"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(150), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    page_count: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), default="uploaded", index=True)
    progress: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    document: Mapped[Document] = relationship(back_populates="versions")
    pages: Mapped[list[Page]] = relationship(
        back_populates="document_version", cascade="all, delete-orphan"
    )
    blocks: Mapped[list[ContentBlock]] = relationship(
        back_populates="document_version", cascade="all, delete-orphan"
    )
    chunks: Mapped[list[Chunk]] = relationship(
        back_populates="document_version", cascade="all, delete-orphan"
    )


class Page(Base):
    __tablename__ = "pages"
    __table_args__ = (UniqueConstraint("document_version_id", "page_number"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    document_version_id: Mapped[str] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE"), index=True
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    width: Mapped[float | None] = mapped_column(Float)
    height: Mapped[float | None] = mapped_column(Float)
    text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    bbox_data: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    ocr_confidence: Mapped[float | None] = mapped_column(Float)
    preview_path: Mapped[str | None] = mapped_column(Text)

    document_version: Mapped[DocumentVersion] = relationship(back_populates="pages")


class ContentBlock(Base):
    __tablename__ = "content_blocks"
    __table_args__ = (UniqueConstraint("document_version_id", "block_index"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    document_version_id: Mapped[str] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE"), index=True
    )
    page_id: Mapped[str | None] = mapped_column(ForeignKey("pages.id", ondelete="SET NULL"))
    block_index: Mapped[int] = mapped_column(Integer, nullable=False)
    block_type: Mapped[str] = mapped_column(String(30), default="paragraph")
    heading_level: Mapped[int | None] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    bbox: Mapped[list[float] | None] = mapped_column(JSON)
    char_start: Mapped[int | None] = mapped_column(Integer)
    char_end: Mapped[int | None] = mapped_column(Integer)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    document_version: Mapped[DocumentVersion] = relationship(back_populates="blocks")


class ImageAsset(Base):
    __tablename__ = "image_assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    document_version_id: Mapped[str] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE"), index=True
    )
    page_number: Mapped[int | None] = mapped_column(Integer)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    bbox: Mapped[list[float] | None] = mapped_column(JSON)
    caption: Mapped[str | None] = mapped_column(Text)
    analysis_text: Mapped[str | None] = mapped_column(Text)
    analysis_model: Mapped[str | None] = mapped_column(String(200))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (
        UniqueConstraint("document_version_id", "ordinal"),
        Index("ix_chunks_version_page", "document_version_id", "page_start"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    document_version_id: Mapped[str] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE"), index=True
    )
    block_id: Mapped[str | None] = mapped_column(
        ForeignKey("content_blocks.id", ondelete="SET NULL"), index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    text_hash: Mapped[str] = mapped_column(String(64), index=True)
    bbox_data: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    document_version: Mapped[DocumentVersion] = relationship(back_populates="chunks")
    embeddings: Mapped[list[Embedding]] = relationship(
        back_populates="chunk", cascade="all, delete-orphan"
    )


class Embedding(Base):
    __tablename__ = "embeddings"
    __table_args__ = (
        UniqueConstraint("chunk_id", "model_profile_id"),
        Index("ix_embeddings_model", "model_name", "dimensions"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    chunk_id: Mapped[str] = mapped_column(ForeignKey("chunks.id", ondelete="CASCADE"), index=True)
    model_profile_id: Mapped[str | None] = mapped_column(
        ForeignKey("model_profiles.id", ondelete="SET NULL")
    )
    model_name: Mapped[str] = mapped_column(String(200), nullable=False)
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    vector: Mapped[list[float]] = mapped_column(VectorType(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    chunk: Mapped[Chunk] = relationship(back_populates="embeddings")


class ModelProfile(TimestampMixin, Base):
    __tablename__ = "model_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    base_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    model_name: Mapped[str] = mapped_column(String(300), nullable=False)
    api_key_encrypted: Mapped[str | None] = mapped_column(Text)
    key_hint: Mapped[str | None] = mapped_column(String(50))
    capabilities: Mapped[dict[str, bool]] = mapped_column(JSON, default=dict, nullable=False)
    default_roles: Mapped[list[str]] = mapped_column(
        JSON,
        default=list,
        server_default="[]",
        nullable=False,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Blueprint(TimestampMixin, Base):
    __tablename__ = "blueprints"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    library_id: Mapped[str] = mapped_column(
        ForeignKey("libraries.id", ondelete="CASCADE"), index=True
    )
    job_id: Mapped[str | None] = mapped_column(
        ForeignKey(
            "generation_jobs.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_blueprints_job_id",
        ),
        index=True,
    )
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="draft")
    source_document_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    content_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    gaps_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)

    knowledge_points: Mapped[list[KnowledgePoint]] = relationship(
        back_populates="blueprint", cascade="all, delete-orphan"
    )


class KnowledgePoint(Base):
    __tablename__ = "knowledge_points"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    blueprint_id: Mapped[str] = mapped_column(
        ForeignKey("blueprints.id", ondelete="CASCADE"), index=True
    )
    parent_id: Mapped[str | None] = mapped_column(
        ForeignKey("knowledge_points.id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    keywords: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)

    blueprint: Mapped[Blueprint] = relationship(back_populates="knowledge_points")
    evidence: Mapped[list[KnowledgeEvidence]] = relationship(
        back_populates="knowledge_point", cascade="all, delete-orphan"
    )


class KnowledgeEvidence(Base):
    __tablename__ = "knowledge_evidence"
    __table_args__ = (UniqueConstraint("knowledge_point_id", "chunk_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    knowledge_point_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_points.id", ondelete="CASCADE"), index=True
    )
    chunk_id: Mapped[str] = mapped_column(ForeignKey("chunks.id", ondelete="CASCADE"), index=True)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    conflict: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text)

    knowledge_point: Mapped[KnowledgePoint] = relationship(back_populates="evidence")


class GenerationJob(TimestampMixin, Base):
    __tablename__ = "generation_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    library_id: Mapped[str] = mapped_column(
        ForeignKey("libraries.id", ondelete="CASCADE"), index=True
    )
    blueprint_id: Mapped[str | None] = mapped_column(
        ForeignKey("blueprints.id", ondelete="SET NULL"), index=True
    )
    parent_job_id: Mapped[str | None] = mapped_column(
        ForeignKey("generation_jobs.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    stage: Mapped[str] = mapped_column(String(60), default="queued")
    progress: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    request_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    target_count: Mapped[int] = mapped_column(Integer, nullable=False)
    accepted_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rejected_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    revision_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    random_seed: Mapped[int] = mapped_column(Integer, nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(50), default="v1", nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    library: Mapped[Library] = relationship(back_populates="jobs")
    events: Mapped[list[JobEvent]] = relationship(
        back_populates="job", cascade="all, delete-orphan", order_by="JobEvent.sequence"
    )
    paper: Mapped[Paper | None] = relationship(back_populates="job", uselist=False)


class JobEvent(Base):
    __tablename__ = "job_events"
    __table_args__ = (UniqueConstraint("job_id", "sequence"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(
        ForeignKey("generation_jobs.id", ondelete="CASCADE"), index=True
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    stage: Mapped[str] = mapped_column(String(60), nullable=False)
    progress: Mapped[float] = mapped_column(Float, nullable=False)
    message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    job: Mapped[GenerationJob] = relationship(back_populates="events")


class Paper(TimestampMixin, Base):
    __tablename__ = "papers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    library_id: Mapped[str] = mapped_column(
        ForeignKey("libraries.id", ondelete="CASCADE"), index=True
    )
    job_id: Mapped[str | None] = mapped_column(
        ForeignKey("generation_jobs.id", ondelete="SET NULL"), unique=True, index=True
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="draft", index=True)
    target_count: Mapped[int] = mapped_column(Integer, nullable=False)
    actual_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    random_seed: Mapped[int] = mapped_column(Integer, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    library: Mapped[Library] = relationship(back_populates="papers")
    job: Mapped[GenerationJob | None] = relationship(back_populates="paper")
    paper_questions: Mapped[list[PaperQuestion]] = relationship(
        back_populates="paper",
        cascade="all, delete-orphan",
        order_by="PaperQuestion.position",
    )
    practice_sessions: Mapped[list[PracticeSession]] = relationship(back_populates="paper")


class Question(TimestampMixin, Base):
    __tablename__ = "questions"
    __table_args__ = (
        UniqueConstraint("library_id", "normalized_hash"),
        Index("ix_questions_library_status", "library_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    library_id: Mapped[str] = mapped_column(
        ForeignKey("libraries.id", ondelete="CASCADE"), index=True
    )
    stem: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    correct_option: Mapped[str] = mapped_column(String(1), nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    knowledge_point: Mapped[str] = mapped_column(String(500), nullable=False)
    difficulty: Mapped[str] = mapped_column(String(20), default="medium")
    status: Mapped[str] = mapped_column(String(30), default="approved", index=True)
    similarity_relaxed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    generation_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    options: Mapped[list[QuestionOption]] = relationship(
        back_populates="question", cascade="all, delete-orphan", order_by="QuestionOption.position"
    )
    citations: Mapped[list[Citation]] = relationship(
        back_populates="question", cascade="all, delete-orphan"
    )
    reviews: Mapped[list[QuestionReview]] = relationship(
        back_populates="question", cascade="all, delete-orphan"
    )


class QuestionOption(Base):
    __tablename__ = "question_options"
    __table_args__ = (UniqueConstraint("question_id", "label"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    question_id: Mapped[str] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), index=True
    )
    label: Mapped[str] = mapped_column(String(1), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    question: Mapped[Question] = relationship(back_populates="options")


class Citation(Base):
    __tablename__ = "citations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    question_id: Mapped[str] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), index=True
    )
    document_version_id: Mapped[str] = mapped_column(
        ForeignKey("document_versions.id", ondelete="RESTRICT"), index=True
    )
    chunk_id: Mapped[str] = mapped_column(ForeignKey("chunks.id", ondelete="RESTRICT"), index=True)
    block_id: Mapped[str | None] = mapped_column(
        ForeignKey("content_blocks.id", ondelete="SET NULL")
    )
    page_number: Mapped[int | None] = mapped_column(Integer)
    rects: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    excerpt: Mapped[str] = mapped_column(Text, nullable=False)
    excerpt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    char_start: Mapped[int | None] = mapped_column(Integer)
    char_end: Mapped[int | None] = mapped_column(Integer)

    question: Mapped[Question] = relationship(back_populates="citations")
    document_version: Mapped[DocumentVersion] = relationship()

    @property
    def document_id(self) -> str:
        return self.document_version.document_id

    @property
    def document_name(self) -> str:
        return self.document_version.document.name

    @property
    def document_type(self) -> str:
        return self.document_version.document.extension

    @property
    def rectangles(self) -> list[dict[str, Any]]:
        """将历史 ``[x0, y0, x1, y1]`` 与新版富坐标统一给前端。"""

        page = next(
            (
                item
                for item in self.document_version.pages
                if item.page_number == self.page_number
            ),
            None,
        )
        result: list[dict[str, Any]] = []
        for value in self.rects:
            if isinstance(value, dict):
                result.append(value)
                continue
            if not isinstance(value, (list, tuple)) or len(value) != 4:
                continue
            x0, y0, x1, y1 = (float(item) for item in value)
            result.append(
                {
                    "x": x0,
                    "y": y0,
                    "width": max(0.0, x1 - x0),
                    "height": max(0.0, y1 - y0),
                    "page_width": page.width if page else None,
                    "page_height": page.height if page else None,
                    "coordinate_system": "top-left",
                }
            )
        return result


class QuestionReview(Base):
    __tablename__ = "question_reviews"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    question_id: Mapped[str] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), index=True
    )
    reviewer_profile_id: Mapped[str | None] = mapped_column(
        ForeignKey("model_profiles.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    chosen_option: Mapped[str | None] = mapped_column(String(1))
    issues: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    question: Mapped[Question] = relationship(back_populates="reviews")


class PaperQuestion(Base):
    __tablename__ = "paper_questions"
    __table_args__ = (
        UniqueConstraint("paper_id", "question_id"),
        UniqueConstraint("paper_id", "position"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    paper_id: Mapped[str] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"), index=True)
    question_id: Mapped[str] = mapped_column(
        ForeignKey("questions.id", ondelete="RESTRICT"), index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    paper: Mapped[Paper] = relationship(back_populates="paper_questions")
    question: Mapped[Question] = relationship()


class PracticeSession(TimestampMixin, Base):
    __tablename__ = "practice_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    paper_id: Mapped[str] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"), index=True)
    mode: Mapped[str] = mapped_column(String(20), default="practice")
    status: Mapped[str] = mapped_column(String(20), default="in_progress", index=True)
    assigned_question_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    current_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    score: Mapped[float | None] = mapped_column(Float)
    correct_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    paper: Mapped[Paper] = relationship(back_populates="practice_sessions")
    answers: Mapped[list[PracticeAnswer]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class PracticeAnswer(Base):
    __tablename__ = "practice_answers"
    __table_args__ = (UniqueConstraint("session_id", "question_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("practice_sessions.id", ondelete="CASCADE"), index=True
    )
    question_id: Mapped[str] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), index=True
    )
    selected_option: Mapped[str] = mapped_column(String(1), nullable=False)
    is_correct: Mapped[bool] = mapped_column(Boolean, nullable=False)
    answered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    session: Mapped[PracticeSession] = relationship(back_populates="answers")
    question: Mapped[Question] = relationship()


# 编排层早期约定使用 Job；保留显式兼容别名。
Job = GenerationJob
