from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from app.tasks import (
    _paper_timestamp,
    _regenerated_question_metadata,
    _select_citation_anchor,
)


def test_select_citation_anchor_prefers_direct_answer_paragraph_over_heading() -> None:
    chunk = SimpleNamespace(
        bbox_data=[
            {
                "block_id": "heading",
                "quote": "信息安全基本属性",
                "page_number": 4,
                "rects": [[10, 10, 100, 30]],
            },
            {
                "block_id": "definition",
                "quote": (
                    "完整性要求信息及处理方法保持准确、完整，"
                    "避免信息在存储或传输过程中被未授权修改。"
                ),
                "page_number": 4,
                "rects": [[10, 40, 520, 90]],
            },
        ]
    )
    question = {
        "stem": "数据在传输过程中被攻击者篡改，最直接破坏了哪项属性？",
        "options": [
            {"label": "A", "text": "保密性"},
            {"label": "B", "text": "完整性"},
            {"label": "C", "text": "可用性"},
            {"label": "D", "text": "真实性"},
        ],
        "correct_option": "B",
        "knowledge_point": "信息安全基本属性之完整性",
        "explanation": "未授权修改会直接破坏信息的完整性。",
    }

    selected = _select_citation_anchor(chunk, question)

    assert selected["block_id"] == "definition"
    assert selected["page_number"] == 4


def test_select_citation_anchor_supports_plain_string_options() -> None:
    chunk = SimpleNamespace(
        bbox_data=[
            {"block_id": "title", "quote": "访问控制"},
            {
                "block_id": "fact",
                "quote": "最小权限原则要求主体只获得完成任务所必需的权限。",
            },
        ]
    )

    selected = _select_citation_anchor(
        chunk,
        {
            "stem": "最小权限原则要求什么？",
            "options": ["授予全部权限", "只授予完成任务所必需的权限", "永久授权", "共享账号"],
            "correct_option": "B",
            "knowledge_point": "最小权限",
            "explanation": "正确答案直接体现最小权限原则。",
        },
    )

    assert selected["block_id"] == "fact"


def test_paper_timestamp_uses_configured_timezone() -> None:
    assert (
        _paper_timestamp(datetime(2026, 7, 31, 5, 36, tzinfo=UTC), "Asia/Shanghai")
        == "2026-07-31 13:36"
    )


def test_regenerated_question_metadata_preserves_audit_context() -> None:
    metadata = _regenerated_question_metadata(
        "old-question",
        {"job_id": "job-1", "document_id": "doc-1", "angle": "旧角度"},
        {"angle": "新角度", "revision": 2},
    )

    assert metadata == {
        "job_id": "job-1",
        "document_id": "doc-1",
        "angle": "新角度",
        "revision": 2,
        "regenerated_from": "old-question",
    }
