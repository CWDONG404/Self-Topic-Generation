"""题目指纹、完全重复与近似重复判定。"""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from enum import StrEnum
from typing import Any

_LATIN_OR_NUMBER = re.compile(r"[a-z0-9]+", re.IGNORECASE)
_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")


def normalize_question_stem(text: str) -> str:
    """规范化题干，消除大小写、全半角、标点和空白造成的伪差异。"""

    normalized = unicodedata.normalize("NFKC", text or "").casefold()
    return "".join(
        char
        for char in normalized
        if not unicodedata.category(char).startswith(("P", "Z", "S", "C"))
    )


def question_stem_hash(text: str) -> str:
    """返回可持久化并建立唯一索引的规范化题干 SHA-256。"""

    return hashlib.sha256(normalize_question_stem(text).encode("utf-8")).hexdigest()


def _lexical_units(text: str) -> set[str]:
    normalized = unicodedata.normalize("NFKC", text or "").casefold()
    units = set(_LATIN_OR_NUMBER.findall(normalized))
    cjk = "".join(_CJK.findall(normalized))
    if len(cjk) == 1:
        units.add(cjk)
    else:
        units.update(cjk[index : index + 2] for index in range(len(cjk) - 1))
    return units


def lexical_similarity(left: str, right: str) -> float:
    """结合字符序列与中英文词元 Jaccard 的轻量相似度。"""

    left_normalized = normalize_question_stem(left)
    right_normalized = normalize_question_stem(right)
    if not left_normalized and not right_normalized:
        return 1.0
    if not left_normalized or not right_normalized:
        return 0.0
    sequence = SequenceMatcher(None, left_normalized, right_normalized, autojunk=False).ratio()
    left_units, right_units = _lexical_units(left), _lexical_units(right)
    union = left_units | right_units
    jaccard = len(left_units & right_units) / len(union) if union else 0.0
    return max(sequence, jaccard)


def cosine_similarity(left: Sequence[float] | None, right: Sequence[float] | None) -> float:
    """计算向量余弦相似度；缺失或维度不一致时返回 0。"""

    if left is None or right is None or len(left) != len(right) or not left:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return 0.0
    return max(-1.0, min(1.0, dot / (left_norm * right_norm)))


@dataclass(frozen=True, slots=True)
class QuestionFingerprint:
    question_id: str | None
    stem: str
    knowledge_point: str = ""
    evidence_ids: frozenset[str] = frozenset()
    angle: str = ""
    embedding: tuple[float, ...] | None = None

    @classmethod
    def from_value(
        cls, value: QuestionFingerprint | Mapping[str, Any] | Any
    ) -> QuestionFingerprint:
        if isinstance(value, cls):
            return value

        def read(*names: str, default: Any = None) -> Any:
            for name in names:
                if isinstance(value, Mapping) and name in value:
                    return value[name]
                if hasattr(value, name):
                    return getattr(value, name)
            return default

        evidence = read("evidence_ids", "citation_ids", default=()) or ()
        embedding = read("embedding", default=None)
        return cls(
            question_id=str(read("question_id", "id", default="")) or None,
            stem=str(read("stem", "question", "question_text", default="")),
            knowledge_point=str(read("knowledge_point", "topic", default="") or ""),
            evidence_ids=frozenset(str(item) for item in evidence),
            angle=str(read("angle", "question_angle", default="") or ""),
            embedding=tuple(float(item) for item in embedding) if embedding else None,
        )


class DuplicateReason(StrEnum):
    ACCEPTED = "accepted"
    EXACT_DUPLICATE = "exact_duplicate"
    HIGH_SIMILARITY = "high_similarity"
    NEAR_DUPLICATE = "near_duplicate"
    RELAXED_MISSING_VARIATION = "relaxed_missing_variation"
    ACCEPTED_RELAXED = "accepted_relaxed"


@dataclass(frozen=True, slots=True)
class DuplicateDecision:
    accepted: bool
    reason: DuplicateReason
    similarity: float = 0.0
    matched_question_id: str | None = None
    similarity_relaxed: bool = False


@dataclass(frozen=True, slots=True)
class DuplicatePolicy:
    """两阶段重复策略。

    - ``hard_threshold`` 以上始终拒绝；
    - 严格阶段在 ``strict_threshold`` 以上拒绝；
    - 同考点且使用同一证据时，同时比较模型给出的设问角度，避免只换题干措辞；
    - 放宽阶段只接受有出处且证据或设问角度确实改变的近似题，并打标。
    """

    strict_threshold: float = 0.82
    hard_threshold: float = 0.95
    concept_threshold: float = 0.65

    def __post_init__(self) -> None:
        if not 0 <= self.strict_threshold < self.hard_threshold <= 1:
            raise ValueError("相似度阈值必须满足 0 <= strict < hard <= 1")
        if not 0 <= self.concept_threshold < self.hard_threshold:
            raise ValueError("考点相似度阈值必须满足 0 <= concept < hard")

    def evaluate(
        self,
        candidate: QuestionFingerprint | Mapping[str, Any] | Any,
        existing: Iterable[QuestionFingerprint | Mapping[str, Any] | Any],
        *,
        relaxed: bool = False,
    ) -> DuplicateDecision:
        current = QuestionFingerprint.from_value(candidate)
        current_hash = question_stem_hash(current.stem)
        best: tuple[float, QuestionFingerprint] | None = None
        best_concept: tuple[float, float, float, QuestionFingerprint] | None = None

        for raw in existing:
            previous = QuestionFingerprint.from_value(raw)
            if current_hash == question_stem_hash(previous.stem):
                return DuplicateDecision(
                    False, DuplicateReason.EXACT_DUPLICATE, 1.0, previous.question_id
                )
            stem_similarity = lexical_similarity(current.stem, previous.stem)
            score = max(
                stem_similarity,
                cosine_similarity(current.embedding, previous.embedding),
            )
            if best is None or score > best[0]:
                best = (score, previous)
            same_knowledge_point = bool(current.knowledge_point.strip()) and (
                normalize_question_stem(current.knowledge_point)
                == normalize_question_stem(previous.knowledge_point)
            )
            same_evidence = bool(current.evidence_ids) and (
                current.evidence_ids == previous.evidence_ids
            )
            angle_similarity = (
                lexical_similarity(current.angle, previous.angle)
                if current.angle.strip() and previous.angle.strip()
                else 0.0
            )
            concept_score = max(score, angle_similarity)
            if (
                same_knowledge_point
                and same_evidence
                and concept_score >= self.concept_threshold
                and (best_concept is None or concept_score > best_concept[0])
            ):
                best_concept = (
                    concept_score,
                    stem_similarity,
                    angle_similarity,
                    previous,
                )

        if best is None:
            return DuplicateDecision(True, DuplicateReason.ACCEPTED)

        score, previous = best
        if score >= self.hard_threshold:
            return DuplicateDecision(
                False, DuplicateReason.HIGH_SIMILARITY, score, previous.question_id
            )
        if best_concept is not None:
            concept_score, stem_similarity, angle_similarity, concept_previous = best_concept
            if concept_score >= self.hard_threshold:
                return DuplicateDecision(
                    False,
                    DuplicateReason.HIGH_SIMILARITY,
                    concept_score,
                    concept_previous.question_id,
                )
            if not relaxed:
                return DuplicateDecision(
                    False,
                    DuplicateReason.NEAR_DUPLICATE,
                    concept_score,
                    concept_previous.question_id,
                )
            changed_angle = (
                bool(current.angle.strip())
                and bool(concept_previous.angle.strip())
                and angle_similarity < self.concept_threshold * 0.55
                and stem_similarity < self.concept_threshold * 0.85
            )
            if not changed_angle:
                return DuplicateDecision(
                    False,
                    DuplicateReason.RELAXED_MISSING_VARIATION,
                    concept_score,
                    concept_previous.question_id,
                )
            return DuplicateDecision(
                True,
                DuplicateReason.ACCEPTED_RELAXED,
                concept_score,
                concept_previous.question_id,
                similarity_relaxed=True,
            )
        if score < self.strict_threshold:
            return DuplicateDecision(True, DuplicateReason.ACCEPTED, score, previous.question_id)
        if not relaxed:
            return DuplicateDecision(
                False, DuplicateReason.NEAR_DUPLICATE, score, previous.question_id
            )

        changed_evidence = (
            bool(current.evidence_ids) and current.evidence_ids != previous.evidence_ids
        )
        changed_angle = (
            bool(current.angle.strip()) and current.angle.strip() != previous.angle.strip()
        )
        if not (changed_evidence or changed_angle):
            return DuplicateDecision(
                False,
                DuplicateReason.RELAXED_MISSING_VARIATION,
                score,
                previous.question_id,
            )
        return DuplicateDecision(
            True,
            DuplicateReason.ACCEPTED_RELAXED,
            score,
            previous.question_id,
            similarity_relaxed=True,
        )
