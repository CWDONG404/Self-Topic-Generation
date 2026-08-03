from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.services.exam_presets import EXAM_PRESET_DISTRIBUTIONS


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Message(BaseModel):
    message: str


class LibraryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)


class LibraryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    archived: bool | None = None


class LibraryRead(ORMModel):
    id: str
    name: str
    description: str | None
    archived: bool
    created_at: datetime
    updated_at: datetime
    document_count: int = 0
    paper_count: int = 0


class DocumentVersionRead(ORMModel):
    id: str
    document_id: str
    version_number: int
    content_hash: str
    mime_type: str
    file_size: int
    page_count: int | None
    status: str
    progress: float
    error: str | None
    metadata_json: dict[str, Any]
    created_at: datetime


class DocumentRead(ORMModel):
    id: str
    library_id: str
    name: str
    role: str
    allow_as_evidence: bool
    extension: str
    mime_type: str
    archived: bool
    created_at: datetime
    updated_at: datetime
    latest_version: DocumentVersionRead | None = None


class DocumentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=500)
    role: Literal["outline", "source"] | None = None
    allow_as_evidence: bool | None = None
    archived: bool | None = None


class ContentBlockRead(ORMModel):
    id: str
    block_index: int
    block_type: str
    heading_level: int | None
    text: str
    bbox: list[float] | None
    char_start: int | None
    char_end: int | None
    metadata_json: dict[str, Any]


class ChunkRead(ORMModel):
    id: str
    document_version_id: str
    block_id: str | None
    ordinal: int
    page_start: int | None
    page_end: int | None
    text: str
    bbox_data: list[dict[str, Any]]
    metadata_json: dict[str, Any]


Provider = Literal["openai_compatible", "ollama"]
ModelRole = Literal["blueprint", "author", "reviewer", "vision", "embedding"]


class ModelProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    provider: Provider
    base_url: str = Field(min_length=1, max_length=1000)
    model_name: str = Field(min_length=1, max_length=300)
    api_key: str | None = Field(default=None, max_length=1000)
    capabilities: dict[str, bool] = Field(default_factory=dict)
    default_roles: list[ModelRole] = Field(default_factory=list)
    enabled: bool = True
    is_default: bool = False

    @field_validator("default_roles")
    @classmethod
    def deduplicate_default_roles(cls, value: list[ModelRole]) -> list[ModelRole]:
        return list(dict.fromkeys(value))

    @model_validator(mode="after")
    def validate_provider(self) -> ModelProfileCreate:
        if self.provider == "openai_compatible" and not self.api_key:
            # 有些自建兼容端点不要求密钥，因此只在 URL 明显为公网 OpenAI 时强制。
            if "api.openai.com" in self.base_url:
                raise ValueError("OpenAI 官方端点必须配置 API Key")
        return self


class ModelProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    provider: Provider | None = None
    base_url: str | None = Field(default=None, min_length=1, max_length=1000)
    model_name: str | None = Field(default=None, min_length=1, max_length=300)
    api_key: str | None = Field(default=None, max_length=1000)
    clear_api_key: bool = False
    capabilities: dict[str, bool] | None = None
    default_roles: list[ModelRole] | None = None
    enabled: bool | None = None
    is_default: bool | None = None

    @field_validator("default_roles")
    @classmethod
    def deduplicate_default_roles(
        cls, value: list[ModelRole] | None
    ) -> list[ModelRole] | None:
        return list(dict.fromkeys(value)) if value is not None else None


class ModelProfileRead(ORMModel):
    id: str
    name: str
    provider: str
    base_url: str
    model_name: str
    capabilities: dict[str, bool]
    default_roles: list[ModelRole]
    enabled: bool
    is_default: bool
    has_api_key: bool = False
    api_key_hint: str | None = None
    created_at: datetime
    updated_at: datetime


class ModelTestResult(BaseModel):
    ok: bool
    latency_ms: int
    message: str
    capabilities: dict[str, bool] = Field(default_factory=dict)


class DocumentAllocation(BaseModel):
    document_id: str
    percentage: int = Field(ge=0, le=100)


class JobCreate(BaseModel):
    library_id: str
    title: str | None = Field(default=None, max_length=500)
    outline_document_ids: list[str] = Field(default_factory=list)
    source_documents: list[DocumentAllocation] = Field(min_length=1)
    target_count: int = Field(default=50, ge=1, le=500)
    model_assignments: dict[str, str] = Field(default_factory=dict)
    execution_mode: Literal["local", "cloud", "mixed"] = "local"
    random_seed: int | None = None
    allow_outline_as_evidence: bool = False
    exam_preset: Literal["cise_v4_2"] | None = None
    topic_distribution: dict[str, int] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_allocations(self) -> JobCreate:
        ids = [item.document_id for item in self.source_documents]
        if len(ids) != len(set(ids)):
            raise ValueError("正文资料不能重复")
        if sum(item.percentage for item in self.source_documents) != 100:
            raise ValueError("正文资料出题比例之和必须为 100%")
        if len(self.outline_document_ids) != len(set(self.outline_document_ids)):
            raise ValueError("重点资料不能重复")
        if self.exam_preset:
            self.topic_distribution = dict(EXAM_PRESET_DISTRIBUTIONS[self.exam_preset])
        if self.topic_distribution:
            if any(not name.strip() for name in self.topic_distribution):
                raise ValueError("知识域名称不能为空")
            if any(value <= 0 or value > 100 for value in self.topic_distribution.values()):
                raise ValueError("知识域比例必须是 1 到 100 的整数")
            if sum(self.topic_distribution.values()) != 100:
                raise ValueError("知识域出题比例之和必须为 100%")
        return self


class JobRead(ORMModel):
    id: str
    library_id: str
    blueprint_id: str | None
    parent_job_id: str | None
    status: str
    stage: str
    progress: float
    request_json: dict[str, Any]
    result_json: dict[str, Any]
    error: str | None
    cancel_requested: bool
    target_count: int
    accepted_count: int
    rejected_count: int
    revision_count: int
    random_seed: int
    prompt_version: str
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class JobEventRead(ORMModel):
    id: str
    job_id: str
    sequence: int
    stage: str
    progress: float
    message: str
    payload: dict[str, Any]
    created_at: datetime


class OptionRead(ORMModel):
    id: str
    label: str
    text: str
    position: int


class CitationRead(ORMModel):
    id: str
    document_id: str
    document_name: str
    document_type: str
    document_version_id: str
    chunk_id: str
    block_id: str | None
    page_number: int | None
    rects: list[Any]
    rectangles: list[dict[str, Any]] = Field(default_factory=list)
    excerpt: str
    excerpt_hash: str
    char_start: int | None
    char_end: int | None


class ReviewRead(ORMModel):
    id: str
    reviewer_profile_id: str | None
    status: str
    chosen_option: str | None
    issues: list[str]
    rationale: str | None
    created_at: datetime


class QuestionRead(ORMModel):
    id: str
    stem: str
    correct_option: str
    explanation: str
    knowledge_point: str
    difficulty: str
    status: str
    similarity_relaxed: bool
    options: list[OptionRead]
    citations: list[CitationRead]
    reviews: list[ReviewRead]
    created_at: datetime
    updated_at: datetime


class QuestionUpdate(BaseModel):
    stem: str | None = Field(default=None, min_length=1)
    options: dict[Literal["A", "B", "C", "D"], str] | None = None
    correct_option: Literal["A", "B", "C", "D"] | None = None
    explanation: str | None = Field(default=None, min_length=1)
    knowledge_point: str | None = Field(default=None, min_length=1, max_length=500)
    difficulty: Literal["easy", "medium", "hard"] | None = None

    @model_validator(mode="after")
    def validate_options(self) -> QuestionUpdate:
        if self.options is not None and set(self.options) != {"A", "B", "C", "D"}:
            raise ValueError("必须完整提供 A、B、C、D 四个选项")
        return self


class PaperRead(ORMModel):
    id: str
    library_id: str
    job_id: str | None
    title: str
    status: str
    target_count: int
    actual_count: int
    random_seed: int
    metadata_json: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class PaperDetail(PaperRead):
    questions: list[QuestionRead] = Field(default_factory=list)


class PracticeSessionCreate(BaseModel):
    paper_id: str
    mode: Literal["practice", "exam"] = "practice"
    question_ids: list[str] | None = None


class WrongAnswerRetryCreate(BaseModel):
    question_ids: list[str] = Field(min_length=1)


class PracticeSessionUpdate(BaseModel):
    current_index: int = Field(ge=0)


class PracticeSessionRead(ORMModel):
    id: str
    paper_id: str
    mode: str
    status: str
    current_index: int
    score: float | None
    correct_count: int
    total_count: int
    created_at: datetime
    updated_at: datetime
    submitted_at: datetime | None


class PracticeQuestionRead(BaseModel):
    id: str
    stem: str
    knowledge_point: str
    difficulty: str
    options: list[OptionRead]
    correct_option: str | None = None
    explanation: str | None = None
    citations: list[CitationRead] = Field(default_factory=list)


class PracticeAnswerRead(ORMModel):
    question_id: str
    selected_option: str
    is_correct: bool | None = None
    answered_at: datetime


class PracticeSessionDetail(PracticeSessionRead):
    questions: list[PracticeQuestionRead] = Field(default_factory=list)
    answers: list[PracticeAnswerRead] = Field(default_factory=list)


class AnswerSubmit(BaseModel):
    question_id: str
    selected_option: Literal["A", "B", "C", "D"]


class AnswerBatch(BaseModel):
    answers: list[AnswerSubmit] = Field(min_length=1)


class AnswerFeedback(BaseModel):
    question_id: str
    selected_option: str
    is_correct: bool | None
    correct_option: str | None = None
    explanation: str | None = None


class PracticeResult(PracticeSessionRead):
    answers: list[PracticeAnswerRead]
    questions: list[QuestionRead]


class BlueprintRead(ORMModel):
    id: str
    library_id: str
    job_id: str | None
    name: str
    version: int
    status: str
    source_document_ids: list[str]
    content_json: dict[str, Any]
    gaps_json: list[dict[str, Any]]
    created_at: datetime
    updated_at: datetime


class BlueprintUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=300)
    status: Literal["draft", "ready", "archived"] | None = None
    content_json: dict[str, Any] | None = None
    gaps_json: list[dict[str, Any]] | None = None
