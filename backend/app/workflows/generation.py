"""三角色 AI 出题工作流与确定性 Supervisor。

LLM 只负责考点蓝图、候选题和独立审题；配额、引用白名单、唯一答案、去重、
返修上限、补题轮次、取消和进度均由确定性代码控制。
"""

from __future__ import annotations

import inspect
import json
import math
import random
import re
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from decimal import Decimal
from typing import Any

from app.services.deduplication import DuplicatePolicy, QuestionFingerprint, question_stem_hash
from app.services.exam_presets import topic_aliases
from app.services.model_gateway import BaseModelGateway, ChatMessage
from app.services.progress import ProgressHook, ProgressReporter, ProgressStage
from app.services.quota import QuotaError, allocate_document_quotas

CancelCheck = Callable[[], bool | Awaitable[bool]]
AuthorBatchHook = Callable[[int, int], None | Awaitable[None]]


class GenerationValidationError(ValueError):
    """出题请求或候选题不满足硬约束。"""


@dataclass(frozen=True, slots=True)
class Evidence:
    evidence_id: str
    document_id: str
    text: str
    chunk_id: str | None = None
    document_version_id: str | None = None
    section_path: tuple[str, ...] = ()
    anchor: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_value(
        cls, value: Evidence | Mapping[str, Any] | Any, default_document_id: str = ""
    ) -> Evidence:
        if isinstance(value, cls):
            return value

        def read(*names: str, default: Any = None) -> Any:
            for name in names:
                if isinstance(value, Mapping) and name in value:
                    return value[name]
                if hasattr(value, name):
                    return getattr(value, name)
            return default

        evidence_id = str(read("evidence_id", "chunk_id", "id", default="")).strip()
        if not evidence_id:
            raise GenerationValidationError("每条正文证据都必须有 evidence_id")
        return cls(
            evidence_id=evidence_id,
            document_id=str(read("document_id", default=default_document_id)),
            text=str(read("text", "content", default="")).strip(),
            chunk_id=str(read("chunk_id", default="") or "") or None,
            document_version_id=str(read("document_version_id", "version_id", default="") or "")
            or None,
            section_path=tuple(str(item) for item in (read("section_path", default=()) or ())),
            anchor=dict(read("anchor", "citation_anchor", default={}) or {}),
            metadata=dict(read("metadata", default={}) or {}),
        )

    def prompt_view(self, max_chars: int = 3500) -> dict[str, Any]:
        """只向模型暴露证据 ID 与正文，不让模型构造坐标。"""

        return {
            "evidence_id": self.evidence_id,
            "document_id": self.document_id,
            "section": " / ".join(self.section_path),
            "text": self.text[:max_chars],
        }


@dataclass(frozen=True, slots=True)
class BlueprintTopic:
    name: str
    weight: float
    keywords: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    rationale: str = ""


@dataclass(frozen=True, slots=True)
class BlueprintPlan:
    topics: tuple[BlueprintTopic, ...]
    coverage_gaps: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()

    @classmethod
    def from_value(cls, value: BlueprintPlan | Mapping[str, Any] | Any) -> BlueprintPlan:
        """从检查点中的纯字典恢复蓝图，不再次调用蓝图 Agent。"""

        if isinstance(value, cls):
            return value

        def read(source: Any, name: str, default: Any = None) -> Any:
            if isinstance(source, Mapping):
                return source.get(name, default)
            return getattr(source, name, default)

        topics = []
        for raw in read(value, "topics", ()) or ():
            name = str(read(raw, "name", "")).strip()
            if not name:
                continue
            topics.append(
                BlueprintTopic(
                    name=name,
                    weight=max(0.0, float(read(raw, "weight", 0) or 0)),
                    keywords=tuple(str(item) for item in (read(raw, "keywords", ()) or ())),
                    evidence_ids=tuple(
                        dict.fromkeys(
                            str(item)
                            for item in (read(raw, "evidence_ids", ()) or ())
                        )
                    ),
                    rationale=str(read(raw, "rationale", "") or ""),
                )
            )
        return cls(
            topics=tuple(topics),
            coverage_gaps=tuple(str(item) for item in (read(value, "coverage_gaps", ()) or ())),
            conflicts=tuple(str(item) for item in (read(value, "conflicts", ()) or ())),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class GenerationRequest:
    total_questions: int
    document_percentages: Mapping[str, Decimal | int | float | str]
    focus_materials: tuple[str, ...] = ()
    topic_percentages: Mapping[str, Decimal | int | float | str] = field(default_factory=dict)
    random_seed: int = 0
    execution_mode: str = "cloud"
    max_rounds: int = 3
    max_revisions: int = 2
    oversample_factor: float = 1.5

    @classmethod
    def from_value(cls, value: GenerationRequest | Mapping[str, Any] | Any) -> GenerationRequest:
        if isinstance(value, cls):
            return value

        def read(*names: str, default: Any = None) -> Any:
            for name in names:
                if isinstance(value, Mapping) and name in value:
                    return value[name]
                if hasattr(value, name):
                    return getattr(value, name)
            return default

        percentages = read("document_percentages", "percentages", default=None)
        if percentages is None:
            raw_documents = read("source_documents", "documents", default=()) or ()
            percentages = {}
            for document in raw_documents:
                if isinstance(document, Mapping):
                    doc_id = document.get("document_id") or document.get("id")
                    percentage = document.get("percentage")
                else:
                    doc_id = getattr(document, "document_id", getattr(document, "id", None))
                    percentage = getattr(document, "percentage", None)
                if doc_id is not None and percentage is not None:
                    percentages[str(doc_id)] = percentage
        if not isinstance(percentages, Mapping):
            raise GenerationValidationError("document_percentages 必须是文档 ID 到百分比的映射")
        focus = read("focus_materials", "focus_texts", default=()) or ()
        topic_percentages = read("topic_distribution", "topic_percentages", default={}) or {}
        if not isinstance(topic_percentages, Mapping):
            raise GenerationValidationError("topic_distribution 必须是知识域到百分比的映射")
        total = read("total_questions", "target_count", "question_count", default=0)
        return cls(
            total_questions=int(total),
            document_percentages={str(key): val for key, val in percentages.items()},
            focus_materials=tuple(str(item) for item in focus),
            topic_percentages={str(key): val for key, val in topic_percentages.items()},
            random_seed=int(read("random_seed", "seed", default=0) or 0),
            execution_mode=str(read("execution_mode", "mode", default="cloud")),
            max_rounds=int(read("max_rounds", default=3)),
            max_revisions=int(read("max_revisions", default=2)),
            oversample_factor=float(read("oversample_factor", default=1.5)),
        )

    def validate(self) -> None:
        if not 1 <= self.total_questions <= 1000:
            raise GenerationValidationError("题量必须在 1 到 1000 之间")
        if self.max_rounds < 1 or self.max_rounds > 10:
            raise GenerationValidationError("补题轮次必须在 1 到 10 之间")
        if self.max_revisions < 0 or self.max_revisions > 5:
            raise GenerationValidationError("单题返修次数必须在 0 到 5 之间")
        if not 1 <= self.oversample_factor <= 3:
            raise GenerationValidationError("候选题放大系数必须在 1 到 3 之间")
        try:
            allocate_document_quotas(self.total_questions, self.document_percentages)
            if self.topic_percentages:
                allocate_document_quotas(self.total_questions, self.topic_percentages)
        except QuotaError as exc:
            raise GenerationValidationError(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class QuestionCandidate:
    question_id: str
    document_id: str
    stem: str
    options: tuple[str, str, str, str]
    correct_option: str
    explanation: str
    knowledge_point: str
    difficulty: str
    evidence_ids: tuple[str, ...]
    angle: str = ""
    similarity_relaxed: bool = False
    review: Mapping[str, Any] = field(default_factory=dict)
    generation_metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_value(
        cls,
        value: Mapping[str, Any] | Any,
        *,
        document_id: str,
        nonce: str = "",
    ) -> QuestionCandidate:
        def read(*names: str, default: Any = None) -> Any:
            for name in names:
                if isinstance(value, Mapping) and name in value:
                    return value[name]
                if hasattr(value, name):
                    return getattr(value, name)
            return default

        stem = str(read("stem", "question", "question_text", default="")).strip()
        raw_options = read("options", default=()) or ()
        if isinstance(raw_options, Mapping):
            options = tuple(str(raw_options.get(label, "")).strip() for label in "ABCD")
        else:
            unpacked: list[str] = []
            for item in raw_options:
                if isinstance(item, Mapping):
                    unpacked.append(str(item.get("text") or item.get("content") or "").strip())
                else:
                    unpacked.append(str(item).strip())
            options = tuple(unpacked)
        raw_answer = read("correct_option", "correct_answer", "answer", default="")
        if (
            isinstance(raw_answer, int)
            and not isinstance(raw_answer, bool)
            and 0 <= raw_answer <= 3
        ):
            correct = "ABCD"[raw_answer]
        else:
            correct = str(raw_answer).strip().upper()
            match = re.search(r"\b([ABCD])\b", correct)
            if match:
                correct = match.group(1)
        evidence_ids = read("evidence_ids", "citation_ids", "citations", default=()) or ()
        normalized_evidence: list[str] = []
        for item in evidence_ids:
            if isinstance(item, Mapping):
                identifier = item.get("evidence_id") or item.get("id")
            else:
                identifier = item
            if identifier:
                normalized_evidence.append(str(identifier))
        generated_id = f"q_{question_stem_hash(stem + nonce)[:24]}"
        padded_options = options[:4]
        # 类型注解要求四项；结构校验会拒绝不满四项，暂时用空项承载模型原始结果。
        padded_options = tuple(padded_options) + tuple("" for _ in range(4 - len(padded_options)))
        padded_options = tuple(
            re.sub(
                r"^\s*[ABCD]\s*[.．、:：)）\]】]\s*",
                "",
                text,
                count=1,
                flags=re.IGNORECASE,
            )
            for text in padded_options
        )
        return cls(
            question_id=str(read("question_id", "id", default="") or generated_id),
            document_id=str(read("document_id", default=document_id) or document_id),
            stem=stem,
            options=padded_options,  # type: ignore[arg-type]
            correct_option=correct,
            explanation=str(read("explanation", "analysis", default="")).strip(),
            knowledge_point=str(read("knowledge_point", "topic", default="")).strip(),
            difficulty=str(read("difficulty", default="medium") or "medium").strip().lower(),
            evidence_ids=tuple(dict.fromkeys(normalized_evidence)),
            angle=str(read("angle", "question_angle", default="")).strip(),
            generation_metadata=dict(read("generation_metadata", "metadata", default={}) or {}),
        )

    def fingerprint(self, embedding: Sequence[float] | None = None) -> QuestionFingerprint:
        return QuestionFingerprint(
            self.question_id,
            self.stem,
            self.knowledge_point,
            frozenset(self.evidence_ids),
            self.angle,
            tuple(float(value) for value in embedding) if embedding else None,
        )

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["options"] = [
            {"label": label, "text": text} for label, text in zip("ABCD", self.options, strict=True)
        ]
        result["citations"] = list(self.evidence_ids)
        return result


@dataclass(frozen=True, slots=True)
class ReviewOutcome:
    passed: bool
    selected_option: str
    feedback: tuple[str, ...]
    evidence_ids: tuple[str, ...] = ()
    raw: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class GenerationResult:
    status: str
    questions: tuple[QuestionCandidate, ...]
    quotas: Mapping[str, int]
    deficits: Mapping[str, int]
    blueprint: BlueprintPlan
    statistics: Mapping[str, int]
    random_seed: int
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "questions": [question.to_dict() for question in self.questions],
            "quotas": dict(self.quotas),
            "deficits": dict(self.deficits),
            "blueprint": self.blueprint.to_dict(),
            "statistics": dict(self.statistics),
            "random_seed": self.random_seed,
            "warnings": list(self.warnings),
        }


BLUEPRINT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "topics": {
            "type": "array",
            "maxItems": 24,
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "weight": {"type": "number"},
                    "keywords": {
                        "type": "array",
                        "maxItems": 6,
                        "items": {"type": "string"},
                    },
                    "evidence_ids": {
                        "type": "array",
                        "maxItems": 8,
                        "items": {"type": "string"},
                    },
                    "rationale": {"type": "string"},
                },
                "required": ["name", "weight", "keywords", "evidence_ids", "rationale"],
                "additionalProperties": False,
            },
        },
        "coverage_gaps": {"type": "array", "items": {"type": "string"}},
        "conflicts": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["topics", "coverage_gaps", "conflicts"],
    "additionalProperties": False,
}


QUESTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "stem": {"type": "string"},
        "options": {"type": "array", "minItems": 4, "maxItems": 4, "items": {"type": "string"}},
        "correct_option": {"type": "string", "enum": ["A", "B", "C", "D"]},
        "explanation": {"type": "string"},
        "knowledge_point": {"type": "string"},
        "difficulty": {"type": "string", "enum": ["easy", "medium", "hard"]},
        "evidence_ids": {"type": "array", "minItems": 1, "items": {"type": "string"}},
        "angle": {"type": "string"},
    },
    "required": [
        "stem",
        "options",
        "correct_option",
        "explanation",
        "knowledge_point",
        "difficulty",
        "evidence_ids",
        "angle",
    ],
    "additionalProperties": False,
}


QUESTION_BATCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"questions": {"type": "array", "items": QUESTION_SCHEMA}},
    "required": ["questions"],
    "additionalProperties": False,
}


REVIEW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "selected_option": {"type": "string", "enum": ["A", "B", "C", "D"]},
        "unique_answer": {"type": "boolean"},
        "supported_by_evidence": {"type": "boolean"},
        "meaningful_assessment": {"type": "boolean"},
        "distractors_valid": {"type": "boolean"},
        "absence_as_false": {"type": "boolean"},
        "quality_score": {"type": "integer", "minimum": 1, "maximum": 5},
        "evidence_ids": {"type": "array", "items": {"type": "string"}},
        "issues": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "selected_option",
        "unique_answer",
        "supported_by_evidence",
        "meaningful_assessment",
        "distractors_valid",
        "absence_as_false",
        "quality_score",
        "evidence_ids",
        "issues",
    ],
    "additionalProperties": False,
}

AUTHOR_BATCH_SIZE = 10


class BlueprintAgent:
    def __init__(self, gateway: BaseModelGateway) -> None:
        self.gateway = gateway

    async def build(
        self,
        focus_materials: Sequence[str],
        evidence: Sequence[Evidence],
        *,
        target_count: int,
        seed: int,
        topic_percentages: Mapping[str, Decimal | int | float | str] | None = None,
    ) -> BlueprintPlan:
        required_distribution = dict(topic_percentages or {})
        system = (
            "你是考点蓝图 Agent。重点资料决定考什么，正文证据决定事实。"
            "把重点映射到给定 evidence_id；无法映射的内容放入 coverage_gaps。"
            "不得发明 evidence_id，权重应为非负数。只返回 JSON。"
        )
        if required_distribution:
            system += (
                "required_topic_distribution 是确定性考试配额。topics 必须逐项使用其中的标准名称，"
                "并为每个知识域映射证据；不得合并、改名或遗漏知识域。"
            )
        grouped: dict[str, list[Evidence]] = {}
        for item in evidence:
            grouped.setdefault(item.document_id, []).append(item)
        balanced_evidence: list[Evidence] = []
        per_document = max(1, 40 // max(1, len(grouped)))
        # 单份长文档也必须首尾均匀取样，否则蓝图只会看到开头章节。
        for values in grouped.values():
            if len(values) <= per_document:
                balanced_evidence.extend(values)
                continue
            if per_document == 1:
                balanced_evidence.append(values[len(values) // 2])
                continue
            positions = {
                round(index * (len(values) - 1) / (per_document - 1))
                for index in range(per_document)
            }
            balanced_evidence.extend(values[index] for index in sorted(positions))
        balanced_evidence = balanced_evidence[:40]
        payload = {
            "target_count": target_count,
            "focus_materials": [text[:8000] for text in focus_materials],
            "authoritative_evidence": [item.prompt_view(1200) for item in balanced_evidence],
            "required_topic_distribution": required_distribution,
        }
        response = await self.gateway.complete_json(
            [
                ChatMessage("system", system),
                ChatMessage("user", json.dumps(payload, ensure_ascii=False)),
            ],
            schema=BLUEPRINT_SCHEMA,
            temperature=0.1,
            seed=seed,
        )
        data = response.data if isinstance(response.data, Mapping) else {}
        known_ids = {item.evidence_id for item in evidence}
        topics: list[BlueprintTopic] = []
        for raw in data.get("topics", ()) or ():
            if not isinstance(raw, Mapping) or not str(raw.get("name") or "").strip():
                continue
            ids = tuple(
                dict.fromkeys(
                    str(item)
                    for item in (raw.get("evidence_ids") or ())
                    if str(item) in known_ids
                )
            )
            topics.append(
                BlueprintTopic(
                    str(raw["name"]).strip(),
                    max(0.0, float(raw.get("weight") or 0)),
                    tuple(str(item) for item in (raw.get("keywords") or ())),
                    ids,
                    str(raw.get("rationale") or ""),
                )
            )
        coverage_gaps = [str(item) for item in (data.get("coverage_gaps") or ())]
        if required_distribution:
            inferred = self._infer_required_topic_evidence(required_distribution, evidence)
            by_name = {topic.name: topic for topic in topics}
            required_topics: list[BlueprintTopic] = []
            for name, percentage in required_distribution.items():
                model_topic = by_name.get(name)
                evidence_ids = tuple(
                    dict.fromkeys(
                        (
                            *(model_topic.evidence_ids if model_topic else ()),
                            *inferred.get(name, ()),
                        )
                    )
                )
                if not evidence_ids:
                    coverage_gaps.append(f"知识域“{name}”未映射到正文证据")
                required_topics.append(
                    BlueprintTopic(
                        name=name,
                        weight=max(0.0, float(percentage)),
                        keywords=(model_topic.keywords if model_topic else topic_aliases(name)),
                        evidence_ids=evidence_ids,
                        rationale=(
                            model_topic.rationale if model_topic else "来自考试预设的确定性配额"
                        ),
                    )
                )
            topics = required_topics
        elif not topics:
            topics = self._fallback_topics(evidence)
        return BlueprintPlan(
            tuple(topics),
            tuple(dict.fromkeys(coverage_gaps)),
            tuple(str(item) for item in (data.get("conflicts") or ())),
        )

    @staticmethod
    def _infer_required_topic_evidence(
        distribution: Mapping[str, Decimal | int | float | str],
        evidence: Sequence[Evidence],
    ) -> dict[str, tuple[str, ...]]:
        """依据章节标题把连续证据归入标准知识域，兼容串讲材料中的简写。"""

        assigned: dict[str, list[str]] = {name: [] for name in distribution}
        current_by_document: dict[str, str] = {}
        ordered = sorted(
            evidence,
            key=lambda item: (item.document_id, int(item.metadata.get("ordinal", 0))),
        )
        for item in ordered:
            section_parts = tuple(part.strip() for part in item.section_path if part.strip())
            first_line = item.text.strip().splitlines()[0].strip() if item.text.strip() else ""
            matched: str | None = None
            for name in distribution:
                aliases = topic_aliases(name)
                if any(alias in section_parts for alias in aliases) or first_line in aliases:
                    matched = name
                    break
            if matched:
                current_by_document[item.document_id] = matched
            current = current_by_document.get(item.document_id)
            if current:
                assigned[current].append(item.evidence_id)
        return {name: tuple(dict.fromkeys(ids)) for name, ids in assigned.items()}

    @staticmethod
    def _fallback_topics(evidence: Sequence[Evidence]) -> list[BlueprintTopic]:
        grouped: dict[str, list[str]] = {}
        for item in evidence:
            name = item.section_path[-1] if item.section_path else "正文知识点"
            grouped.setdefault(name, []).append(item.evidence_id)
        count = max(1, len(grouped))
        return [
            BlueprintTopic(name, 1 / count, evidence_ids=tuple(ids))
            for name, ids in grouped.items()
        ]


class QuestionAuthorAgent:
    def __init__(self, gateway: BaseModelGateway) -> None:
        self.gateway = gateway

    async def generate(
        self,
        *,
        document_id: str,
        count: int,
        evidence: Sequence[Evidence],
        topics: Sequence[BlueprintTopic],
        seed: int,
        variation_nonce: str,
        feedback: Sequence[str] = (),
        batch_progress: AuthorBatchHook | None = None,
        cancel_check: CancelCheck | None = None,
    ) -> list[QuestionCandidate]:
        system = (
            "你是四选一单选题出题 Agent。每题必须独立可读、只有一个正确答案，"
            "解析说明正确项为何正确及主要干扰项为何错误。只可引用输入中的 evidence_id，"
            "不得生成页码、坐标或不存在的出处。不要使用“根据以上材料”等依赖上下文的措辞。"
            "禁止把‘资料中是否列出、提到或出现’作为答案判定逻辑；资料没有提到某概念，"
            "不代表该概念错误。每个干扰项必须能由证据或稳定、无争议的专业知识说明为何错误，"
            "不能只是随意拼凑几个材料外名词。优先设计情境应用、流程顺序、方案比较、风险判断、"
            "因果分析或计算题；可以用稳定的领域常识扩展情境，但决定正确答案的关键前提必须能"
            "回溯到给定证据。纯名单识别题仅在名单本身具有明确规范意义且无法合理情境化时使用。"
            "相同考点应改变设问角度。只返回 JSON。"
        )
        generated: list[QuestionCandidate] = []
        starts = list(range(0, count, AUTHOR_BATCH_SIZE))
        for batch_index, start in enumerate(starts):
            if cancel_check is not None:
                cancelled = cancel_check()
                if inspect.isawaitable(cancelled):
                    cancelled = await cancelled
                if cancelled:
                    break
            batch_count = min(AUTHOR_BATCH_SIZE, count - start)
            batch_nonce = f"{variation_nonce}-batch-{batch_index}"
            payload = {
                "document_id": document_id,
                "requested_count": batch_count,
                "variation_nonce": batch_nonce,
                "topic_hints": [asdict(topic) for topic in topics],
                "evidence": [item.prompt_view() for item in evidence],
                "revision_feedback": list(feedback),
            }
            response = await self.gateway.complete_json(
                [
                    ChatMessage("system", system),
                    ChatMessage("user", json.dumps(payload, ensure_ascii=False)),
                ],
                schema=QUESTION_BATCH_SCHEMA,
                temperature=0.75,
                seed=seed + batch_index,
            )
            data = response.data
            raw_questions = data.get("questions", ()) if isinstance(data, Mapping) else data
            if not isinstance(raw_questions, Sequence) or isinstance(
                raw_questions, (str, bytes)
            ):
                continue
            generated.extend(
                QuestionCandidate.from_value(
                    raw,
                    document_id=document_id,
                    nonce=f"{batch_nonce}:{index}",
                )
                for index, raw in enumerate(raw_questions[:batch_count])
                if isinstance(raw, Mapping)
            )
            if batch_progress is not None:
                progress_result = batch_progress(batch_index + 1, len(starts))
                if inspect.isawaitable(progress_result):
                    await progress_result
        return generated

    async def revise(
        self,
        question: QuestionCandidate,
        *,
        evidence: Sequence[Evidence],
        feedback: Sequence[str],
        seed: int,
        revision: int,
    ) -> QuestionCandidate | None:
        revised = await self.generate(
            document_id=question.document_id,
            count=1,
            evidence=evidence,
            topics=(
                BlueprintTopic(
                    question.knowledge_point or "待修订考点", 1, evidence_ids=question.evidence_ids
                ),
            ),
            seed=seed,
            variation_nonce=f"revision-{question.question_id}-{revision}",
            feedback=(
                "以下是待修订题目：" + json.dumps(question.to_dict(), ensure_ascii=False),
                *feedback,
            ),
        )
        return revised[0] if revised else None


class QuestionReviewerAgent:
    def __init__(self, gateway: BaseModelGateway) -> None:
        self.gateway = gateway

    async def review(
        self,
        question: QuestionCandidate,
        *,
        evidence: Sequence[Evidence],
        seed: int,
    ) -> ReviewOutcome:
        # 刻意不传出题 Agent 的答案与解析，先独立作答，再由 Supervisor 比对。
        known = {item.evidence_id for item in evidence}
        deterministic_issues = validate_question(question, known)
        if deterministic_issues:
            return ReviewOutcome(
                False,
                "",
                deterministic_issues,
                (),
                {
                    "meaningful_assessment": False,
                    "distractors_valid": False,
                    "absence_as_false": True,
                    "quality_score": 1,
                },
            )
        prompt = {
            "stem": question.stem,
            "options": {label: text for label, text in zip("ABCD", question.options, strict=True)},
            "evidence": [item.prompt_view() for item in evidence],
        }
        response = await self.gateway.complete_json(
            [
                ChatMessage(
                    "system",
                    "你是独立审题 Agent。先脱离出题者结论独立作答，再严格评估题目质量。"
                    "检查唯一答案、题意、直接证据、干扰项和考查价值。以下情况必须判失败："
                    "(1) 只问哪些名称在资料中列出/提到/出现，属于机械名单识别；"
                    "(2) 把资料没有提到某概念当作该选项错误，证据沉默不等于事实为假；"
                    "(3) 干扰项只是任意拼凑、明显荒谬或无法逐项说明错误；"
                    "(4) 只复述一句原文，不考查理解、应用、比较、顺序、因果、风险判断或计算。"
                    "允许使用稳定且无争议的专业常识来理解情境，但正确答案的关键前提仍须有"
                    "给定 evidence_id 支撑。meaningful_assessment 仅在题目具有实际训练价值时"
                    "为 true；"
                    "distractors_valid 仅在每个错误项都因事实或逻辑错误而错误时为 true；"
                    "absence_as_false 表示题目是否利用‘材料未出现’来判错；quality_score 1-5，"
                    "低于 3 不得通过。不得参考出题者答案，不得发明 evidence_id。只返回 JSON。",
                ),
                ChatMessage("user", json.dumps(prompt, ensure_ascii=False)),
            ],
            schema=REVIEW_SCHEMA,
            temperature=0,
            seed=seed,
        )
        data = response.data if isinstance(response.data, Mapping) else {}
        selected = str(data.get("selected_option") or "").upper()
        unique = data.get("unique_answer") is True
        supported = data.get("supported_by_evidence") is True
        meaningful = data.get("meaningful_assessment") is True
        distractors_valid = data.get("distractors_valid") is True
        absence_as_false = data.get("absence_as_false") is True
        quality_score = int(data.get("quality_score") or 0)
        evidence_ids = tuple(
            str(item) for item in (data.get("evidence_ids") or ()) if str(item) in known
        )
        issues = [str(item) for item in (data.get("issues") or ())]
        if selected != question.correct_option:
            issues.append(
                f"独立作答为 {selected or '未知'}，与出题答案 {question.correct_option} 不一致"
            )
        if not unique:
            issues.append("审题 Agent 未确认答案唯一")
        if not supported or not evidence_ids:
            issues.append("审题 Agent 未确认正文证据支持")
        if not meaningful:
            issues.append("题目考查价值不足，偏向机械记忆或原文名单识别")
        if not distractors_valid:
            issues.append("干扰项缺乏独立事实依据或区分度")
        if absence_as_false:
            issues.append("错误选项依赖‘资料未提及即为错误’的无效逻辑")
        if quality_score < 3:
            issues.append(f"题目质量评分过低（{quality_score}/5）")
        passed = (
            selected == question.correct_option
            and unique
            and supported
            and bool(evidence_ids)
            and meaningful
            and distractors_valid
            and not absence_as_false
            and quality_score >= 3
        )
        return ReviewOutcome(
            passed, selected, tuple(dict.fromkeys(issues)), evidence_ids, dict(data)
        )


_CONTEXT_DEPENDENT = re.compile(
    r"根据(?:上述|以上|所给|这份)(?:材料|文档|内容|上下文)|(?:in|from)\s+the\s+(?:above\s+)?(?:document|context)",
    re.IGNORECASE,
)

_MATERIAL_META_STEM = re.compile(
    r"(?:资料|材料|讲义|文档)(?:中|里|所)?(?:列出|列举|提到|提及|出现|包含|包括|未列出|未提到|未出现)",
    re.IGNORECASE,
)


def validate_question(
    question: QuestionCandidate, allowed_evidence_ids: set[str]
) -> tuple[str, ...]:
    """不调用 LLM 的候选题质量门。"""

    issues: list[str] = []
    if len(question.stem) < 6:
        issues.append("题干过短")
    if _CONTEXT_DEPENDENT.search(question.stem):
        issues.append("题干依赖外部上下文")
    if _MATERIAL_META_STEM.search(question.stem):
        issues.append("题目以资料是否提及作为判定依据，考查价值不足")
    if len(question.options) != 4 or any(not item.strip() for item in question.options):
        issues.append("必须有四个非空选项")
    normalized_options = {re.sub(r"\s+", "", item).casefold() for item in question.options}
    if len(normalized_options) != 4:
        issues.append("四个选项必须互不相同")
    if question.correct_option not in "ABCD" or len(question.correct_option) != 1:
        issues.append("正确答案必须是 A、B、C、D 之一")
    if not question.explanation:
        issues.append("缺少答案解析")
    if not question.knowledge_point:
        issues.append("缺少知识点")
    if question.difficulty not in {"easy", "medium", "hard"}:
        issues.append("难度必须是 easy、medium 或 hard")
    if not question.evidence_ids:
        issues.append("至少需要一条正文出处")
    unknown = set(question.evidence_ids) - allowed_evidence_ids
    if unknown:
        issues.append("引用了不存在的 evidence_id：" + ", ".join(sorted(unknown)))
    return tuple(issues)


_OPTION_LABEL_REFERENCE = re.compile(r"(?<![A-Za-z0-9_])([ABCD])(?![A-Za-z0-9_])")


def _remap_option_label_references(text: str, label_mapping: Mapping[str, str]) -> str:
    """随选项换位同步改写解析中的 A/B/C/D 引用，避免标签与选项内容错位。"""

    return _OPTION_LABEL_REFERENCE.sub(
        lambda match: label_mapping.get(match.group(1), match.group(1)),
        text,
    )


def _balance_correct_option_positions(
    questions: Sequence[QuestionCandidate], *, seed: int
) -> list[QuestionCandidate]:
    """确定性地均衡正确答案位置，并保留原题语义与审查结论。"""

    if not questions:
        return []
    randomizer = random.Random(seed ^ 0x4B1D_5EED)
    cycle = list("ABCD")
    randomizer.shuffle(cycle)
    targets = [cycle[index % len(cycle)] for index in range(len(questions))]
    randomizer.shuffle(targets)

    balanced: list[QuestionCandidate] = []
    for question, target in zip(questions, targets, strict=True):
        source = question.correct_option
        if source not in "ABCD" or target not in "ABCD":
            balanced.append(question)
            continue
        label_mapping = {label: label for label in "ABCD"}
        options = list(question.options)
        if source != target:
            source_index = "ABCD".index(source)
            target_index = "ABCD".index(target)
            options[source_index], options[target_index] = (
                options[target_index],
                options[source_index],
            )
            label_mapping[source], label_mapping[target] = target, source
        review = dict(question.review)
        selected = str(review.get("selected_option") or "")
        if selected in label_mapping:
            review["selected_option"] = label_mapping[selected]
        balanced.append(
            replace(
                question,
                options=tuple(options),  # type: ignore[arg-type]
                correct_option=target,
                explanation=_remap_option_label_references(
                    question.explanation, label_mapping
                ),
                review=review,
                generation_metadata={
                    **question.generation_metadata,
                    "answer_position_original": source,
                    "answer_position_balanced": target,
                },
            )
        )
    return balanced


class GenerationSupervisor:
    """无自由发挥的 Supervisor，控制整个出题任务。"""

    def __init__(
        self,
        blueprint_agent: BlueprintAgent,
        author_agent: QuestionAuthorAgent,
        reviewer_agent: QuestionReviewerAgent,
        *,
        duplicate_policy: DuplicatePolicy | None = None,
        embedding_gateway: BaseModelGateway | None = None,
    ) -> None:
        self.blueprint_agent = blueprint_agent
        self.author_agent = author_agent
        self.reviewer_agent = reviewer_agent
        self.duplicate_policy = duplicate_policy or DuplicatePolicy()
        self.embedding_gateway = embedding_gateway

    @classmethod
    def from_gateways(
        cls,
        *,
        blueprint: BaseModelGateway,
        author: BaseModelGateway,
        reviewer: BaseModelGateway,
        embedding: BaseModelGateway | None = None,
    ) -> GenerationSupervisor:
        return cls(
            BlueprintAgent(blueprint),
            QuestionAuthorAgent(author),
            QuestionReviewerAgent(reviewer),
            embedding_gateway=embedding,
        )

    async def run(
        self,
        request: GenerationRequest | Mapping[str, Any] | Any,
        evidence_by_document: Mapping[str, Sequence[Evidence | Mapping[str, Any] | Any]],
        *,
        historical_questions: Iterable[QuestionFingerprint | Mapping[str, Any] | Any] = (),
        progress_hook: ProgressHook | None = None,
        cancel_check: CancelCheck | None = None,
        prebuilt_blueprint: BlueprintPlan | Mapping[str, Any] | Any | None = None,
    ) -> GenerationResult:
        spec = GenerationRequest.from_value(request)
        reporter = ProgressReporter(progress_hook)
        if prebuilt_blueprint is None:
            await reporter.emit(
                ProgressStage.VALIDATING,
                message="正在校验出题参数",
                target=spec.total_questions,
            )
        spec.validate()
        quotas = allocate_document_quotas(spec.total_questions, spec.document_percentages)
        evidence_map = {
            str(document_id): tuple(Evidence.from_value(item, str(document_id)) for item in values)
            for document_id, values in evidence_by_document.items()
        }
        if prebuilt_blueprint is None:
            await reporter.emit(
                ProgressStage.VALIDATING,
                fraction=1,
                message="参数校验完成",
                target=spec.total_questions,
                payload={"quotas": quotas},
            )
        if await self._is_cancelled(cancel_check):
            return await self._cancelled_result(reporter, quotas, spec)

        flat_evidence = [
            item for document_id in quotas for item in evidence_map.get(document_id, ())
        ]
        if prebuilt_blueprint is None:
            await reporter.emit(ProgressStage.BLUEPRINT, message="正在理解重点资料并映射正文")
            blueprint = await self.blueprint_agent.build(
                spec.focus_materials,
                flat_evidence,
                target_count=spec.total_questions,
                seed=spec.random_seed,
                topic_percentages=spec.topic_percentages,
            )
            await reporter.emit(
                ProgressStage.BLUEPRINT,
                fraction=1,
                message="考点蓝图已生成",
                payload={
                    "topics": len(blueprint.topics),
                    "coverage_gaps": list(blueprint.coverage_gaps),
                },
            )
        else:
            blueprint = BlueprintPlan.from_value(prebuilt_blueprint)
            await reporter.emit(
                ProgressStage.BLUEPRINT,
                fraction=1,
                message="已从检查点恢复考点蓝图",
                payload={
                    "topics": len(blueprint.topics),
                    "coverage_gaps": list(blueprint.coverage_gaps),
                    "checkpoint_reused": True,
                },
            )
        await reporter.emit(ProgressStage.RETRIEVING, message="正在准备权威正文证据")

        randomizer = random.Random(spec.random_seed)
        accepted: list[QuestionCandidate] = []
        fingerprints = [QuestionFingerprint.from_value(item) for item in historical_questions]
        embedding_cache: dict[str, tuple[float, ...]] = {}
        if self.embedding_gateway and fingerprints:
            for start in range(0, len(fingerprints), 64):
                batch = fingerprints[start : start + 64]
                vectors = await self.embedding_gateway.embed_texts([item.stem for item in batch])
                if len(vectors) != len(batch):
                    raise GenerationValidationError("历史题目 Embedding 返回数量不一致")
                for offset, vector in enumerate(vectors):
                    position = start + offset
                    resolved = tuple(float(value) for value in vector)
                    fingerprints[position] = replace(fingerprints[position], embedding=resolved)
                    embedding_cache[question_stem_hash(batch[offset].stem)] = resolved
        deficits: dict[str, int] = {}
        warnings: list[str] = list(blueprint.coverage_gaps)
        statistics = {"generated": 0, "accepted": 0, "rejected": 0, "revised": 0}
        await reporter.emit(
            ProgressStage.RETRIEVING,
            fraction=1,
            message="正文证据准备完成",
            payload={"evidence_count": len(flat_evidence)},
        )

        for document_id, quota in quotas.items():
            if quota == 0:
                continue
            if await self._is_cancelled(cancel_check):
                return await self._cancelled_result(
                    reporter, quotas, spec, accepted, blueprint, statistics, deficits, warnings
                )
            document_evidence = list(evidence_map.get(document_id, ()))
            if not document_evidence:
                deficits[document_id] = quota
                warning = f"文档 {document_id} 没有可用正文证据，缺少 {quota} 题"
                warnings.append(warning)
                await reporter.emit(
                    ProgressStage.GENERATING,
                    fraction=len(accepted) / spec.total_questions,
                    message=warning,
                    accepted=len(accepted),
                    target=spec.total_questions,
                    warning=warning,
                    current_document=document_id,
                )
                continue

            allowed_ids = {item.evidence_id for item in document_evidence}
            topics = self._topics_for_document(blueprint, allowed_ids)
            topic_quotas = (
                allocate_document_quotas(quota, spec.topic_percentages)
                if spec.topic_percentages
                else {}
            )
            topics_by_name = {topic.name: topic for topic in topics}
            for round_index in range(spec.max_rounds):
                current_document_count = sum(
                    1 for question in accepted if question.document_id == document_id
                )
                missing = quota - current_document_count
                if missing <= 0:
                    break
                if await self._is_cancelled(cancel_check):
                    return await self._cancelled_result(
                        reporter, quotas, spec, accepted, blueprint, statistics, deficits, warnings
                    )
                relaxed = round_index == spec.max_rounds - 1
                nonce = (
                    f"{spec.random_seed}-{document_id}-{round_index}-"
                    f"{randomizer.getrandbits(64):016x}"
                )
                await reporter.emit(
                    ProgressStage.GENERATING,
                    fraction=len(accepted) / spec.total_questions,
                    message=f"正在生成第 {round_index + 1} 轮候选题",
                    accepted=len(accepted),
                    target=spec.total_questions,
                    generated=statistics["generated"],
                    rejected=statistics["rejected"],
                    revised=statistics["revised"],
                    current_document=document_id,
                    payload={"round": round_index + 1, "relaxed": relaxed},
                )

                async def report_author_batch(
                    completed: int,
                    total: int,
                    *,
                    accepted_before: int = len(accepted),
                    missing_count: int = missing,
                    current_document_id: str = document_id,
                    generation_round: int = round_index,
                ) -> None:
                    estimated = accepted_before + (
                        missing_count * 0.2 * completed / max(1, total)
                    )
                    await reporter.emit(
                        ProgressStage.GENERATING,
                        fraction=estimated / spec.total_questions,
                        message=f"候选题生成中（批次 {completed}/{total}）",
                        accepted=accepted_before,
                        target=spec.total_questions,
                        generated=statistics["generated"],
                        rejected=statistics["rejected"],
                        revised=statistics["revised"],
                        current_document=current_document_id,
                        payload={
                            "round": generation_round + 1,
                            "batch": completed,
                            "batch_total": total,
                        },
                    )

                candidate_evidence: dict[str, Sequence[Evidence]] = {}
                if topic_quotas:
                    candidates = []
                    topic_quota_items = list(topic_quotas.items())
                    topic_quota_completed = 0
                    for topic_name, topic_quota in topic_quota_items:
                        accepted_for_topic = sum(
                            1
                            for question in accepted
                            if question.document_id == document_id
                            and question.generation_metadata.get("exam_domain") == topic_name
                        )
                        topic_missing = topic_quota - accepted_for_topic
                        if topic_missing <= 0:
                            continue
                        topic = topics_by_name.get(topic_name) or BlueprintTopic(
                            topic_name,
                            float(spec.topic_percentages[topic_name]),
                        )
                        topic_evidence = self._sample_evidence(
                            document_evidence,
                            randomizer,
                            max_items=24,
                            preferred_ids=set(topic.evidence_ids),
                        )
                        topic_candidate_count = max(
                            topic_missing,
                            math.ceil(topic_missing * spec.oversample_factor),
                        )
                        # 候选题会先按知识域全部生成、再统一审查；这里预留生成/审题
                        # 区间的 15% 展示知识域与批次进度，避免长文档任务在 25% 假性卡住。
                        generation_fraction = (
                            len(accepted) + (topic_quota_completed * 0.15)
                        ) / spec.total_questions
                        await reporter.emit(
                            ProgressStage.GENERATING,
                            fraction=generation_fraction,
                            message=f"正在生成知识域“{topic_name}”候选题",
                            accepted=len(accepted),
                            target=spec.total_questions,
                            current_document=document_id,
                            payload={
                                "exam_domain": topic_name,
                                "domain_target": topic_quota,
                                "domain_accepted": accepted_for_topic,
                                "round": round_index + 1,
                            },
                        )

                        async def report_topic_batch(
                            completed: int,
                            total: int,
                            *,
                            accepted_before: int = len(accepted),
                            completed_quota: int = topic_quota_completed,
                            current_topic_quota: int = topic_quota,
                            current_topic_name: str = topic_name,
                            current_document_id: str = document_id,
                            generation_round: int = round_index,
                        ) -> None:
                            topic_equivalent = completed_quota + (
                                current_topic_quota * completed / max(1, total)
                            )
                            await reporter.emit(
                                ProgressStage.GENERATING,
                                fraction=(
                                    accepted_before + (topic_equivalent * 0.15)
                                )
                                / spec.total_questions,
                                message=(
                                    f"知识域“{current_topic_name}”候选题生成中"
                                    f"（批次 {completed}/{total}）"
                                ),
                                accepted=accepted_before,
                                target=spec.total_questions,
                                generated=statistics["generated"],
                                rejected=statistics["rejected"],
                                revised=statistics["revised"],
                                current_document=current_document_id,
                                current_topic=current_topic_name,
                                payload={
                                    "exam_domain": current_topic_name,
                                    "domain_target": current_topic_quota,
                                    "batch": completed,
                                    "batch_total": total,
                                    "round": generation_round + 1,
                                },
                            )

                        generated_for_topic = await self.author_agent.generate(
                            document_id=document_id,
                            count=topic_candidate_count,
                            evidence=topic_evidence,
                            topics=(topic,),
                            seed=randomizer.randrange(0, 2**31),
                            variation_nonce=f"{nonce}-{topic_name}",
                            batch_progress=report_topic_batch,
                            cancel_check=cancel_check,
                        )
                        for candidate in generated_for_topic:
                            tagged = replace(
                                candidate,
                                generation_metadata={
                                    **candidate.generation_metadata,
                                    "exam_domain": topic_name,
                                },
                            )
                            candidates.append(tagged)
                            candidate_evidence[tagged.question_id] = topic_evidence
                        topic_quota_completed += topic_quota
                else:
                    candidate_count = max(
                        missing, math.ceil(missing * spec.oversample_factor)
                    )
                    sampled_evidence = self._sample_evidence(
                        document_evidence,
                        randomizer,
                        max_items=16,
                        preferred_ids={
                            evidence_id for topic in topics for evidence_id in topic.evidence_ids
                        },
                    )
                    candidates = await self.author_agent.generate(
                        document_id=document_id,
                        count=candidate_count,
                        evidence=sampled_evidence,
                        topics=topics,
                        seed=randomizer.randrange(0, 2**31),
                        variation_nonce=nonce,
                        batch_progress=report_author_batch,
                        cancel_check=cancel_check,
                    )
                    candidate_evidence = {
                        candidate.question_id: sampled_evidence for candidate in candidates
                    }
                statistics["generated"] += len(candidates)

                for candidate_index, original in enumerate(candidates):
                    current_document_count = sum(
                        1 for question in accepted if question.document_id == document_id
                    )
                    if current_document_count >= quota:
                        break
                    exam_domain = str(original.generation_metadata.get("exam_domain") or "")
                    if exam_domain and sum(
                        1
                        for question in accepted
                        if question.document_id == document_id
                        and question.generation_metadata.get("exam_domain") == exam_domain
                    ) >= topic_quotas.get(exam_domain, 0):
                        continue
                    if await self._is_cancelled(cancel_check):
                        return await self._cancelled_result(
                            reporter,
                            quotas,
                            spec,
                            accepted,
                            blueprint,
                            statistics,
                            deficits,
                            warnings,
                        )
                    current = replace(original, document_id=document_id)
                    passed = False
                    last_issues: tuple[str, ...] = ()
                    for revision in range(spec.max_revisions + 1):
                        issues = list(validate_question(current, allowed_ids))
                        current_embedding: tuple[float, ...] | None = None
                        if self.embedding_gateway:
                            cache_key = question_stem_hash(current.stem)
                            current_embedding = embedding_cache.get(cache_key)
                            if current_embedding is None:
                                vectors = await self.embedding_gateway.embed_texts([current.stem])
                                if len(vectors) != 1 or not vectors[0]:
                                    raise GenerationValidationError(
                                        "候选题 Embedding 返回数量或维度无效"
                                    )
                                current_embedding = tuple(float(value) for value in vectors[0])
                                embedding_cache[cache_key] = current_embedding
                        current_fingerprint = current.fingerprint(current_embedding)
                        duplicate = self.duplicate_policy.evaluate(
                            current_fingerprint, fingerprints, relaxed=relaxed
                        )
                        if not duplicate.accepted:
                            issues.append(
                                f"重复检查未通过：{duplicate.reason.value} "
                                f"({duplicate.similarity:.3f})"
                            )
                        if not issues:
                            cited = [
                                item
                                for item in document_evidence
                                if item.evidence_id in current.evidence_ids
                            ]
                            await reporter.emit(
                                ProgressStage.REVIEWING,
                                fraction=len(accepted) / spec.total_questions,
                                message=f"正在独立审查第 {len(accepted) + 1} 题",
                                accepted=len(accepted),
                                target=spec.total_questions,
                                generated=statistics["generated"],
                                rejected=statistics["rejected"],
                                revised=statistics["revised"],
                                current_document=document_id,
                            )
                            review = await self.reviewer_agent.review(
                                current,
                                evidence=cited,
                                seed=randomizer.randrange(0, 2**31),
                            )
                            if review.passed:
                                current = replace(
                                    current,
                                    similarity_relaxed=duplicate.similarity_relaxed,
                                    review={
                                        "passed": True,
                                        "selected_option": review.selected_option,
                                        "evidence_ids": list(review.evidence_ids),
                                        "issues": [],
                                    },
                                    generation_metadata={
                                        **current.generation_metadata,
                                        "round": round_index + 1,
                                        "revision": revision,
                                        "variation_nonce": nonce,
                                    },
                                )
                                accepted.append(current)
                                fingerprints.append(current_fingerprint)
                                statistics["accepted"] += 1
                                passed = True
                                await reporter.emit(
                                    ProgressStage.REVIEWING,
                                    fraction=len(accepted) / spec.total_questions,
                                    message=f"已通过 {len(accepted)} / {spec.total_questions} 题",
                                    accepted=len(accepted),
                                    target=spec.total_questions,
                                    generated=statistics["generated"],
                                    rejected=statistics["rejected"],
                                    revised=statistics["revised"],
                                    current_document=document_id,
                                )
                                break
                            issues.extend(review.feedback or ("审题未通过",))
                        last_issues = tuple(dict.fromkeys(issues))
                        if revision >= spec.max_revisions:
                            break
                        revised = await self.author_agent.revise(
                            current,
                            evidence=candidate_evidence.get(
                                original.question_id, document_evidence
                            ),
                            feedback=last_issues,
                            seed=randomizer.randrange(0, 2**31),
                            revision=revision + 1,
                        )
                        statistics["revised"] += 1
                        if revised is None:
                            break
                        current = replace(
                            revised,
                            document_id=document_id,
                            generation_metadata={
                                **revised.generation_metadata,
                                **({"exam_domain": exam_domain} if exam_domain else {}),
                            },
                        )
                    if not passed:
                        statistics["rejected"] += 1
                        await reporter.emit(
                            ProgressStage.REVIEWING,
                            fraction=len(accepted) / spec.total_questions,
                            message="候选题已淘汰",
                            accepted=len(accepted),
                            target=spec.total_questions,
                            generated=statistics["generated"],
                            rejected=statistics["rejected"],
                            revised=statistics["revised"],
                            current_document=document_id,
                            payload={
                                "issues": list(last_issues),
                                "candidate_index": candidate_index,
                            },
                        )

            current_document_count = sum(
                1 for question in accepted if question.document_id == document_id
            )
            if current_document_count < quota:
                deficits[document_id] = quota - current_document_count

        await reporter.emit(
            ProgressStage.ASSEMBLING,
            message="正在组装试卷并核对最终配额",
            accepted=len(accepted),
            target=spec.total_questions,
            generated=statistics["generated"],
            rejected=statistics["rejected"],
            revised=statistics["revised"],
        )
        # 选项位置由 Supervisor 做确定性均衡，避免模型偏好造成整卷答案集中在同一标签。
        accepted = _balance_correct_option_positions(accepted, seed=spec.random_seed)
        # 防止模型返回导致的题目顺序偏差；最终整体洗牌。
        randomizer.shuffle(accepted)
        status = (
            "completed" if len(accepted) == spec.total_questions and not deficits else "partial"
        )
        if status == "partial":
            warnings.append(
                "证据或质量门不足，已生成部分完成试卷；系统没有继续无限重试或编造题目。"
            )
        result = GenerationResult(
            status,
            tuple(accepted),
            quotas,
            deficits,
            blueprint,
            dict(statistics),
            spec.random_seed,
            tuple(dict.fromkeys(warnings)),
        )
        await reporter.emit(
            ProgressStage.COMPLETED if status == "completed" else ProgressStage.PARTIAL,
            fraction=1,
            message="试卷生成完成" if status == "completed" else "试卷部分完成",
            accepted=len(accepted),
            target=spec.total_questions,
            generated=statistics["generated"],
            rejected=statistics["rejected"],
            revised=statistics["revised"],
            payload={"deficits": deficits},
        )
        return result

    @staticmethod
    def _sample_evidence(
        evidence: Sequence[Evidence],
        randomizer: random.Random,
        *,
        max_items: int,
        preferred_ids: set[str] | None = None,
    ) -> list[Evidence]:
        if len(evidence) <= max_items:
            result = list(evidence)
            randomizer.shuffle(result)
            return result
        preferred = [
            item for item in evidence if preferred_ids and item.evidence_id in preferred_ids
        ]
        randomizer.shuffle(preferred)
        selected = preferred[: max_items // 2]
        selected_ids = {item.evidence_id for item in selected}
        remaining = [item for item in evidence if item.evidence_id not in selected_ids]
        selected.extend(randomizer.sample(remaining, max_items - len(selected)))
        return selected

    @staticmethod
    def _topics_for_document(
        blueprint: BlueprintPlan, allowed_ids: set[str]
    ) -> tuple[BlueprintTopic, ...]:
        topics = tuple(
            topic
            for topic in blueprint.topics
            if not topic.evidence_ids or set(topic.evidence_ids) & allowed_ids
        )
        return topics or (BlueprintTopic("正文知识点", 1, evidence_ids=tuple(sorted(allowed_ids))),)

    @staticmethod
    async def _is_cancelled(cancel_check: CancelCheck | None) -> bool:
        if cancel_check is None:
            return False
        result = cancel_check()
        if inspect.isawaitable(result):
            result = await result
        return bool(result)

    @staticmethod
    async def _cancelled_result(
        reporter: ProgressReporter,
        quotas: Mapping[str, int],
        spec: GenerationRequest,
        accepted: Sequence[QuestionCandidate] = (),
        blueprint: BlueprintPlan | None = None,
        statistics: Mapping[str, int] | None = None,
        deficits: Mapping[str, int] | None = None,
        warnings: Sequence[str] = (),
    ) -> GenerationResult:
        stats = dict(
            statistics or {"generated": 0, "accepted": len(accepted), "rejected": 0, "revised": 0}
        )
        plan = blueprint or BlueprintPlan(())
        remaining = dict(deficits or {})
        for document_id, quota in quotas.items():
            made = sum(1 for question in accepted if question.document_id == document_id)
            if made < quota:
                remaining[document_id] = quota - made
        await reporter.emit(
            ProgressStage.CANCELLED,
            fraction=1,
            message="任务已取消",
            accepted=len(accepted),
            target=spec.total_questions,
            generated=stats.get("generated", 0),
            rejected=stats.get("rejected", 0),
            revised=stats.get("revised", 0),
            payload={"deficits": remaining},
        )
        return GenerationResult(
            "cancelled",
            tuple(accepted),
            dict(quotas),
            remaining,
            plan,
            stats,
            spec.random_seed,
            tuple(warnings),
        )
