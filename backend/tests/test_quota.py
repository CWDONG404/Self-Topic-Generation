from __future__ import annotations

import pytest

from app.services.deduplication import (
    DuplicatePolicy,
    DuplicateReason,
    QuestionFingerprint,
    normalize_question_stem,
    question_stem_hash,
)
from app.services.quota import QuotaError, allocate_document_quotas, largest_remainder_allocate


def test_largest_remainder_is_exact_and_stable() -> None:
    assert allocate_document_quotas(50, {"环境安全": 12, "监管": 33, "密码": 55}) == {
        "环境安全": 6,
        "监管": 17,
        "密码": 27,
    }
    allocation = allocate_document_quotas(7, {"先传入": 33, "第二个": 33, "较大余数": 34})
    assert allocation == {"先传入": 2, "第二个": 2, "较大余数": 3}
    assert sum(allocation.values()) == 7


def test_generic_weights_do_not_need_to_sum_to_one_hundred() -> None:
    assert largest_remainder_allocate(5, {"a": 1, "b": 1, "c": 1}) == {
        "a": 2,
        "b": 2,
        "c": 1,
    }


@pytest.mark.parametrize(
    "total,percentages",
    [
        (10, {"a": 20, "b": 70}),
        (10, {"a": -1, "b": 101}),
        (-1, {"a": 100}),
        (10, {}),
    ],
)
def test_invalid_quota_is_rejected(total: int, percentages: dict[str, int]) -> None:
    with pytest.raises(QuotaError):
        allocate_document_quotas(total, percentages)


def test_exact_duplicate_ignores_punctuation_whitespace_and_width() -> None:
    left = "访问控制的核心目标是什么？"
    right = " 访问控制 的核心目标是什么? "
    assert normalize_question_stem(left) == normalize_question_stem(right)
    assert question_stem_hash(left) == question_stem_hash(right)
    decision = DuplicatePolicy().evaluate(
        QuestionFingerprint("new", left),
        [QuestionFingerprint("old", right)],
    )
    assert not decision.accepted
    assert decision.reason is DuplicateReason.EXACT_DUPLICATE


def test_near_duplicate_can_only_relax_after_material_variation() -> None:
    policy = DuplicatePolicy(strict_threshold=0.6, hard_threshold=0.99)
    old = QuestionFingerprint(
        "old",
        "访问控制机制的主要安全目标是什么",
        "访问控制",
        frozenset({"e1"}),
        "定义",
    )
    candidate = QuestionFingerprint(
        "new",
        "访问控制机制的主要安全目标通常是什么",
        "访问控制",
        frozenset({"e2"}),
        "场景判断",
    )
    assert policy.evaluate(candidate, [old], relaxed=False).reason is DuplicateReason.NEAR_DUPLICATE
    relaxed = policy.evaluate(candidate, [old], relaxed=True)
    assert relaxed.accepted
    assert relaxed.similarity_relaxed


def test_same_evidence_and_similar_angle_is_a_concept_duplicate() -> None:
    policy = DuplicatePolicy()
    old = QuestionFingerprint(
        "old",
        "某系统的防护时间为30秒，检测和响应共需35秒，系统状态如何？",
        "P2DR 时间模型",
        frozenset({"e1"}),
        "给定时间参数计算暴露时间并判断系统安全性",
    )
    candidate = QuestionFingerprint(
        "new",
        "若防护时间为30分钟，检测与响应合计35分钟，应如何判断？",
        "P2DR 时间模型",
        frozenset({"e1"}),
        "给定参数计算暴露时间并判断安全性",
    )

    strict = policy.evaluate(candidate, [old], relaxed=False)
    relaxed = policy.evaluate(candidate, [old], relaxed=True)

    assert strict.reason is DuplicateReason.NEAR_DUPLICATE
    assert not relaxed.accepted
    assert relaxed.reason is DuplicateReason.RELAXED_MISSING_VARIATION


def test_same_evidence_can_relax_when_question_angle_materially_changes() -> None:
    policy = DuplicatePolicy(strict_threshold=0.82, hard_threshold=0.99)
    old = QuestionFingerprint(
        "old",
        "访问控制机制的主要安全目标是什么",
        "访问控制",
        frozenset({"e1"}),
        "定义识别",
        (1.0, 0.0),
    )
    candidate = QuestionFingerprint(
        "new",
        "员工离职后，管理员首先应处置其哪些系统权限？",
        "访问控制",
        frozenset({"e1"}),
        "企业人员离职后的权限回收场景",
        (0.9, 0.435889894),
    )

    relaxed = policy.evaluate(candidate, [old], relaxed=True)

    assert relaxed.accepted
    assert relaxed.similarity_relaxed
