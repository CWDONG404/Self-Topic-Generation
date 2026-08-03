from __future__ import annotations

import asyncio
import json
import sys
from collections import Counter
from types import ModuleType, SimpleNamespace
from typing import Any

from app.services.exam_presets import CISE_V42_DISTRIBUTION
from app.services.model_gateway import CallableGateway
from app.workflows.generation import (
    AUTHOR_BATCH_SIZE,
    BlueprintPlan,
    BlueprintTopic,
    Evidence,
    GenerationRequest,
    GenerationSupervisor,
    QuestionAuthorAgent,
    QuestionCandidate,
    validate_question,
)
from app.workflows.langgraph_workflow import (
    _invoke_resumable,
    _request_dict,
    build_generation_graph,
)


def test_three_role_workflow_obeys_quota_citations_and_progress() -> None:
    author_counter = 0

    async def blueprint_handler(messages: Any, **_: Any) -> dict[str, Any]:
        payload = json.loads(messages[-1].content)
        evidence_ids = [item["evidence_id"] for item in payload["authoritative_evidence"]]
        duplicated_evidence_ids = [evidence_ids[0], *evidence_ids]
        return {
            "topics": [
                {
                    "name": "安全机制",
                    "weight": 1,
                    "keywords": ["安全"],
                    "evidence_ids": duplicated_evidence_ids,
                    "rationale": "重点资料要求掌握安全机制",
                }
            ],
            "coverage_gaps": [],
            "conflicts": [],
        }

    templates = [
        "身份鉴别机制最直接降低了下列哪类风险？",
        "审计日志在安全事件调查中主要发挥什么作用？",
        "备份恢复演练最适合验证组织的哪项能力？",
        "最小权限原则要求管理员如何分配访问权限？",
        "纵深防御策略为何需要部署多层安全控制？",
        "完整性校验最适合发现下列哪种异常？",
    ]

    async def author_handler(messages: Any, **_: Any) -> dict[str, Any]:
        nonlocal author_counter
        payload = json.loads(messages[-1].content)
        evidence_id = payload["evidence"][0]["evidence_id"]
        questions = []
        for _index in range(payload["requested_count"]):
            stem = templates[author_counter % len(templates)]
            author_counter += 1
            questions.append(
                {
                    "stem": stem,
                    "options": [
                        "消除全部风险",
                        "降低对应安全风险",
                        "替代所有管理制度",
                        "保证永不发生事件",
                    ],
                    "correct_option": "B",
                    "explanation": "B 直接符合证据；其余选项均作出了绝对化或越界表述。",
                    "knowledge_point": "安全机制",
                    "difficulty": "medium",
                    "evidence_ids": [evidence_id],
                    "angle": stem[:6],
                }
            )
        return {"questions": questions}

    async def reviewer_handler(messages: Any, **_: Any) -> dict[str, Any]:
        payload = json.loads(messages[-1].content)
        return {
            "selected_option": "B",
            "unique_answer": True,
            "supported_by_evidence": True,
            "meaningful_assessment": True,
            "distractors_valid": True,
            "absence_as_false": False,
            "quality_score": 4,
            "evidence_ids": [payload["evidence"][0]["evidence_id"]],
            "issues": [],
        }

    supervisor = GenerationSupervisor.from_gateways(
        blueprint=CallableGateway(blueprint_handler, model_name="blueprint"),
        author=CallableGateway(author_handler, model_name="author"),
        reviewer=CallableGateway(reviewer_handler, model_name="reviewer"),
    )
    request = GenerationRequest(
        total_questions=3,
        document_percentages={"doc-a": 34, "doc-b": 66},
        focus_materials=("身份鉴别、审计与恢复是考试重点。",),
        random_seed=20260730,
    )
    evidence = {
        "doc-a": [Evidence("ev-a", "doc-a", "身份鉴别能够降低冒用身份的风险。")],
        "doc-b": [Evidence("ev-b", "doc-b", "审计支持追溯，备份恢复保证业务连续性。")],
    }
    events = []

    result = asyncio.run(
        supervisor.run(request, evidence, progress_hook=lambda event: events.append(event))
    )

    assert result.status == "completed"
    assert result.quotas == {"doc-a": 1, "doc-b": 2}
    assert len(result.blueprint.topics[0].evidence_ids) == len(
        set(result.blueprint.topics[0].evidence_ids)
    )
    assert len(result.questions) == 3
    assert sum(question.document_id == "doc-a" for question in result.questions) == 1
    assert sum(question.document_id == "doc-b" for question in result.questions) == 2
    assert all(len(question.options) == 4 for question in result.questions)
    assert all(question.review.get("passed") for question in result.questions)
    assert len({question.correct_option for question in result.questions}) == 3
    assert all(
        question.review.get("selected_option") == question.correct_option
        for question in result.questions
    )
    assert all(
        f"{question.correct_option} 直接符合证据" in question.explanation
        for question in result.questions
    )
    assert all(question.evidence_ids[0] in {"ev-a", "ev-b"} for question in result.questions)
    assert [event.sequence for event in events] == list(range(1, len(events) + 1))
    assert [event.progress for event in events] == sorted(event.progress for event in events)
    assert events[-1].progress == 100


def test_cise_v42_preset_enforces_exact_domain_distribution() -> None:
    evidence = [
        Evidence(
            f"ev-{index}",
            "doc",
            f"{name}的权威正文证据，包含该知识域可考查的概念、流程和判断规则。",
            section_path=(name,),
            metadata={"ordinal": index},
        )
        for index, name in enumerate(CISE_V42_DISTRIBUTION, start=1)
    ]
    evidence_by_domain = {
        item.section_path[0]: item.evidence_id for item in evidence
    }
    generated_counts: Counter[str] = Counter()
    stem_templates = (
        "在{domain}实施准备阶段，负责人首先应确认哪项控制目标？",
        "审计人员评价{domain}有效性时，最应关注下列哪项证据？",
        "某组织调整{domain}流程后，哪种做法最符合持续改进要求？",
        "针对{domain}出现的异常事件，下列哪项处置顺序最恰当？",
        "设计{domain}控制措施时，以下哪个原则应当优先满足？",
        "管理层复核{domain}工作成果时，应使用哪类判定依据？",
        "当{domain}资源受到限制时，哪项风险处置决策更合理？",
        "为验证{domain}机制是否生效，最适合开展哪项活动？",
        "关于{domain}职责分工，下列描述中哪一项最准确？",
        "在{domain}生命周期结束前，必须完成哪项收尾工作？",
        "发生跨部门{domain}争议时，应依据什么确定最终责任？",
        "比较两种{domain}方案时，哪项指标最能反映实际保障能力？",
    )

    async def blueprint(messages: Any, **_: Any) -> dict[str, Any]:
        payload = json.loads(messages[-1].content)
        return {
            "topics": [
                {
                    "name": name,
                    "weight": percentage,
                    "keywords": [name],
                    "evidence_ids": [evidence_by_domain[name]],
                    "rationale": "CISE V4.2 标准配额",
                }
                for name, percentage in payload["required_topic_distribution"].items()
            ],
            "coverage_gaps": [],
            "conflicts": [],
        }

    async def author(messages: Any, **_: Any) -> dict[str, Any]:
        payload = json.loads(messages[-1].content)
        domain = payload["topic_hints"][0]["name"]
        evidence_id = evidence_by_domain[domain]
        questions = []
        for _ in range(payload["requested_count"]):
            generated_counts[domain] += 1
            serial = generated_counts[domain]
            questions.append(
                {
                    "stem": stem_templates[(serial - 1) % len(stem_templates)].format(
                        domain=domain
                    ),
                    "options": ["符合规范", "完全相反", "无关概念", "证据未涉及"],
                    "correct_option": "A",
                    "explanation": "A 与该知识域正文证据一致，其他选项不符合证据。",
                    "knowledge_point": f"{domain}考点{serial}",
                    "difficulty": "medium",
                    "evidence_ids": [evidence_id],
                    "angle": f"{domain}-angle-{serial}",
                }
            )
        return {"questions": questions}

    async def reviewer(messages: Any, **_: Any) -> dict[str, Any]:
        payload = json.loads(messages[-1].content)
        return {
            "selected_option": "A",
            "unique_answer": True,
            "supported_by_evidence": True,
            "meaningful_assessment": True,
            "distractors_valid": True,
            "absence_as_false": False,
            "quality_score": 4,
            "evidence_ids": [payload["evidence"][0]["evidence_id"]],
            "issues": [],
        }

    supervisor = GenerationSupervisor.from_gateways(
        blueprint=CallableGateway(blueprint),
        author=CallableGateway(author),
        reviewer=CallableGateway(reviewer),
    )
    events = []
    result = asyncio.run(
        supervisor.run(
            {
                "total_questions": 100,
                "document_percentages": {"doc": 100},
                "topic_distribution": CISE_V42_DISTRIBUTION,
                "random_seed": 42,
                "max_rounds": 1,
                "max_revisions": 0,
                "oversample_factor": 1,
            },
            {"doc": evidence},
            progress_hook=events.append,
        )
    )

    assert result.status == "completed"
    assert len(result.questions) == 100
    assert Counter(
        question.generation_metadata["exam_domain"] for question in result.questions
    ) == Counter(CISE_V42_DISTRIBUTION)
    generation_events = [event for event in events if event.stage.value == "generating"]
    assert any("知识域" in event.message for event in generation_events)
    assert max(event.progress for event in generation_events) >= 34
    assert [event.progress for event in events] == sorted(event.progress for event in events)


def test_langgraph_checkpoint_preserves_topic_distribution() -> None:
    payload = _request_dict(
        GenerationRequest(
            total_questions=100,
            document_percentages={"doc": 100},
            topic_percentages=CISE_V42_DISTRIBUTION,
        )
    )

    restored = GenerationRequest.from_value(payload)
    assert restored.topic_percentages == {
        name: str(percentage) for name, percentage in CISE_V42_DISTRIBUTION.items()
    }


def test_material_presence_question_is_rejected_as_low_value() -> None:
    question = QuestionCandidate(
        question_id="q-low-value",
        document_id="doc",
        stem="资料中列出的常用备份介质包括下列哪一组？",
        options=("磁带与硬盘", "云盘与光盘", "纸带与内存", "缓存与日志"),
        correct_option="A",
        explanation="资料列出了磁带与硬盘。",
        knowledge_point="备份介质",
        difficulty="easy",
        evidence_ids=("e1",),
    )

    issues = validate_question(question, {"e1"})

    assert "题目以资料是否提及作为判定依据，考查价值不足" in issues


def test_missing_evidence_returns_partial_instead_of_inventing_questions() -> None:
    async def handler(messages: Any, **_: Any) -> dict[str, Any]:
        if "考点蓝图" in messages[0].content:
            return {"topics": [], "coverage_gaps": ["缺少正文"], "conflicts": []}
        raise AssertionError("没有正文时不应调用出题或审题 Agent")

    gateway = CallableGateway(handler)
    supervisor = GenerationSupervisor.from_gateways(
        blueprint=gateway,
        author=gateway,
        reviewer=gateway,
    )
    result = asyncio.run(
        supervisor.run(
            GenerationRequest(2, {"doc": 100}),
            {"doc": []},
        )
    )
    assert result.status == "partial"
    assert result.questions == ()
    assert result.deficits == {"doc": 2}
    assert any("没有可用正文证据" in warning for warning in result.warnings)


def test_author_splits_large_requests_into_bounded_batches() -> None:
    requested_counts: list[int] = []

    async def author(messages: Any, **_: Any) -> dict[str, Any]:
        payload = json.loads(messages[-1].content)
        requested_counts.append(payload["requested_count"])
        return {
            "questions": [
                {
                    "stem": (
                        f"第 {len(requested_counts)} 批第 {index + 1} 道"
                        "安全机制题目的答案是什么？"
                    ),
                    "options": ["选项一", "选项二", "选项三", "选项四"],
                    "correct_option": "A",
                    "explanation": "A 正确。",
                    "knowledge_point": "安全机制",
                    "difficulty": "easy",
                    "evidence_ids": ["ev-1"],
                    "angle": f"batch-{len(requested_counts)}-{index}",
                }
                for index in range(payload["requested_count"])
            ]
        }

    count = AUTHOR_BATCH_SIZE * 2 + 3
    generated = asyncio.run(
        QuestionAuthorAgent(CallableGateway(author)).generate(
            document_id="doc",
            count=count,
            evidence=[Evidence("ev-1", "doc", "正文证据")],
            topics=[BlueprintTopic("安全机制", 1, evidence_ids=("ev-1",))],
            seed=42,
            variation_nonce="large-request",
        )
    )

    assert requested_counts == [AUTHOR_BATCH_SIZE, AUTHOR_BATCH_SIZE, 3]
    assert len(generated) == count
    assert len({question.question_id for question in generated}) == count


def test_author_stops_before_next_batch_after_cancel() -> None:
    calls = 0

    async def author(messages: Any, **_: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        payload = json.loads(messages[-1].content)
        return {
            "questions": [
                {
                    "stem": f"批次取消测试第 {index} 题？",
                    "options": ["一", "二", "三", "四"],
                    "correct_option": "A",
                    "explanation": "测试解析。",
                    "knowledge_point": "取消",
                    "difficulty": "easy",
                    "evidence_ids": ["ev-1"],
                    "angle": f"cancel-{index}",
                }
                for index in range(payload["requested_count"])
            ]
        }

    generated = asyncio.run(
        QuestionAuthorAgent(CallableGateway(author)).generate(
            document_id="doc",
            count=AUTHOR_BATCH_SIZE * 2,
            evidence=[Evidence("ev-1", "doc", "正文证据")],
            topics=[BlueprintTopic("取消", 1, evidence_ids=("ev-1",))],
            seed=42,
            variation_nonce="cancel-between-batches",
            cancel_check=lambda: calls >= 1,
        )
    )

    assert calls == 1
    assert len(generated) == AUTHOR_BATCH_SIZE


def test_question_candidate_removes_redundant_option_label_prefixes() -> None:
    candidate = QuestionCandidate.from_value(
        {
            "stem": "以下哪项正确？",
            "options": ["D. 第一项", "B、第二项", "A）第三项", "C: 第四项"],
            "correct_option": "A",
        },
        document_id="doc",
    )
    unmatched = QuestionCandidate.from_value(
        {
            "stem": "下列等级中哪项正确？",
            "options": ["B2 等级", "A股市场", "CISP 认证", "DLP 系统"],
            "correct_option": "A",
        },
        document_id="doc",
    )

    assert candidate.options == ("第一项", "第二项", "第三项", "第四项")
    assert unmatched.options == ("B2 等级", "A股市场", "CISP 认证", "DLP 系统")


def test_cancel_check_stops_before_model_generation() -> None:
    calls = 0

    async def handler(messages: Any, **_: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return {"topics": [], "coverage_gaps": [], "conflicts": []}

    gateway = CallableGateway(handler)
    supervisor = GenerationSupervisor.from_gateways(
        blueprint=gateway,
        author=gateway,
        reviewer=gateway,
    )
    result = asyncio.run(
        supervisor.run(
            GenerationRequest(1, {"doc": 100}),
            {"doc": [Evidence("e1", "doc", "正文证据")]},
            cancel_check=lambda: True,
        )
    )
    assert result.status == "cancelled"
    assert calls == 0


def test_prebuilt_blueprint_is_reused_without_calling_blueprint_agent() -> None:
    blueprint_calls = 0

    async def forbidden_blueprint(messages: Any, **_: Any) -> dict[str, Any]:
        nonlocal blueprint_calls
        blueprint_calls += 1
        raise AssertionError("恢复后不应重新调用蓝图 Agent")

    async def author(messages: Any, **_: Any) -> dict[str, Any]:
        payload = json.loads(messages[-1].content)
        return {
            "questions": [
                {
                    "stem": "最小权限原则要求如何分配系统访问权限？",
                    "options": ["全部开放", "按工作需要授予", "永久授权", "共享管理员账号"],
                    "correct_option": "B",
                    "explanation": "最小权限要求仅授予完成工作所必需的权限。",
                    "knowledge_point": "最小权限",
                    "difficulty": "easy",
                    "evidence_ids": [payload["evidence"][0]["evidence_id"]],
                    "angle": "原则应用",
                }
            ]
        }

    async def reviewer(messages: Any, **_: Any) -> dict[str, Any]:
        payload = json.loads(messages[-1].content)
        return {
            "selected_option": "B",
            "unique_answer": True,
            "supported_by_evidence": True,
            "meaningful_assessment": True,
            "distractors_valid": True,
            "absence_as_false": False,
            "quality_score": 4,
            "evidence_ids": [payload["evidence"][0]["evidence_id"]],
            "issues": [],
        }

    supervisor = GenerationSupervisor.from_gateways(
        blueprint=CallableGateway(forbidden_blueprint),
        author=CallableGateway(author),
        reviewer=CallableGateway(reviewer),
    )
    checkpointed_blueprint = BlueprintPlan((BlueprintTopic("最小权限", 1, evidence_ids=("e1",)),))
    events = []
    result = asyncio.run(
        supervisor.run(
            GenerationRequest(1, {"doc": 100}),
            {"doc": [Evidence("e1", "doc", "权限应按工作需要进行最小化授予。")]},
            prebuilt_blueprint=checkpointed_blueprint.to_dict(),
            progress_hook=events.append,
        )
    )

    assert result.status == "completed"
    assert result.blueprint == checkpointed_blueprint
    assert blueprint_calls == 0
    assert any(event.payload.get("checkpoint_reused") for event in events)


def test_langgraph_has_checkpoint_boundaries_for_key_business_stages(monkeypatch: Any) -> None:
    class FakeStateGraph:
        latest: FakeStateGraph | None = None

        def __init__(self, state_type: Any) -> None:
            self.state_type = state_type
            self.nodes: dict[str, Any] = {}
            self.edges: list[tuple[str, str]] = []
            FakeStateGraph.latest = self

        def add_node(self, name: str, function: Any) -> None:
            self.nodes[name] = function

        def add_edge(self, source: str, target: str) -> None:
            self.edges.append((source, target))

        def compile(self, *, checkpointer: Any = None) -> FakeStateGraph:
            self.checkpointer = checkpointer
            return self

    langgraph_package = ModuleType("langgraph")
    langgraph_package.__path__ = []  # type: ignore[attr-defined]
    graph_module = ModuleType("langgraph.graph")
    graph_module.START = "START"
    graph_module.END = "END"
    graph_module.StateGraph = FakeStateGraph
    monkeypatch.setitem(sys.modules, "langgraph", langgraph_package)
    monkeypatch.setitem(sys.modules, "langgraph.graph", graph_module)

    gateway = CallableGateway(lambda *_args, **_kwargs: {})
    supervisor = GenerationSupervisor.from_gateways(
        blueprint=gateway,
        author=gateway,
        reviewer=gateway,
    )
    graph = build_generation_graph(supervisor, checkpointer="persistent-saver")

    assert set(graph.nodes) == {"validate", "blueprint", "generate_review", "finalize"}
    assert graph.edges == [
        ("START", "validate"),
        ("validate", "blueprint"),
        ("blueprint", "generate_review"),
        ("generate_review", "finalize"),
        ("finalize", "END"),
    ]
    assert graph.checkpointer == "persistent-saver"


def test_resumable_invocation_uses_pending_checkpoint_instead_of_starting_over() -> None:
    class FakeGraph:
        def __init__(self) -> None:
            self.inputs: list[Any] = []

        async def aget_state(self, config: Any) -> Any:
            return SimpleNamespace(
                values={"blueprint": {"topics": []}, "workflow_stage": "blueprint_ready"},
                next=("generate_review",),
            )

        async def ainvoke(self, value: Any, *, config: Any) -> dict[str, Any]:
            self.inputs.append(value)
            return {"result": {"status": "completed"}}

    graph = FakeGraph()
    result = asyncio.run(
        _invoke_resumable(
            graph,
            {"workflow_stage": "queued"},
            config={"configurable": {"thread_id": "job-1"}},
            checkpointer=object(),
        )
    )
    assert result["result"]["status"] == "completed"
    assert graph.inputs == [None]
