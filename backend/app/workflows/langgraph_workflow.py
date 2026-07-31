"""关键业务阶段可检查点的 LangGraph 出题编排。

图只编排单次出题任务：``validate -> blueprint -> generate_review -> finalize``。
其中蓝图以纯字典写入图状态；如果生成/审题阶段失败，使用相同 thread_id 和持久化
checkpointer 再次调用时会从待执行节点恢复，不会重新请求蓝图 Agent。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, TypedDict

from app.services.deduplication import QuestionFingerprint
from app.services.progress import ProgressReporter, ProgressStage
from app.services.quota import allocate_document_quotas
from app.workflows.generation import (
    BlueprintPlan,
    Evidence,
    GenerationRequest,
    GenerationSupervisor,
)


class LangGraphUnavailable(RuntimeError):
    pass


class GenerationGraphState(TypedDict, total=False):
    # 所有可恢复字段均为纯 JSON 风格值；避免把数据库对象或模型客户端写进检查点。
    request: Mapping[str, Any]
    evidence_by_document: Mapping[str, Sequence[Mapping[str, Any]]]
    historical_questions: Sequence[Mapping[str, Any]]
    quotas: Mapping[str, int]
    blueprint: Mapping[str, Any]
    generation_result: Mapping[str, Any]
    result: Mapping[str, Any]
    workflow_stage: str


def _request_dict(request: GenerationRequest | Mapping[str, Any] | Any) -> dict[str, Any]:
    spec = GenerationRequest.from_value(request)
    return {
        "total_questions": spec.total_questions,
        "document_percentages": {
            str(document_id): str(value) for document_id, value in spec.document_percentages.items()
        },
        "focus_materials": list(spec.focus_materials),
        "random_seed": spec.random_seed,
        "execution_mode": spec.execution_mode,
        "max_rounds": spec.max_rounds,
        "max_revisions": spec.max_revisions,
        "oversample_factor": spec.oversample_factor,
    }


def _evidence_dict(evidence: Evidence) -> dict[str, Any]:
    return {
        "evidence_id": evidence.evidence_id,
        "document_id": evidence.document_id,
        "text": evidence.text,
        "chunk_id": evidence.chunk_id,
        "document_version_id": evidence.document_version_id,
        "section_path": list(evidence.section_path),
        "anchor": dict(evidence.anchor),
        "metadata": dict(evidence.metadata),
    }


def _evidence_map_dict(
    evidence_by_document: Mapping[str, Sequence[Evidence | Mapping[str, Any] | Any]],
) -> dict[str, list[dict[str, Any]]]:
    return {
        str(document_id): [
            _evidence_dict(Evidence.from_value(item, str(document_id))) for item in values
        ]
        for document_id, values in evidence_by_document.items()
    }


def _history_dict(values: Sequence[Any]) -> list[dict[str, Any]]:
    result = []
    for value in values:
        fingerprint = QuestionFingerprint.from_value(value)
        result.append(
            {
                "question_id": fingerprint.question_id,
                "stem": fingerprint.stem,
                "knowledge_point": fingerprint.knowledge_point,
                "evidence_ids": sorted(fingerprint.evidence_ids),
                "angle": fingerprint.angle,
                "embedding": list(fingerprint.embedding) if fingerprint.embedding else None,
            }
        )
    return result


def build_generation_graph(
    supervisor: GenerationSupervisor,
    *,
    progress_hook: Any = None,
    cancel_check: Any = None,
    checkpointer: Any = None,
) -> Any:
    """构建四阶段图；每条边之后均可由 LangGraph checkpointer 保存状态。"""

    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError as exc:  # pragma: no cover - optional production dependency
        raise LangGraphUnavailable("未安装 langgraph；可直接运行确定性 Supervisor") from exc

    async def validate_node(state: GenerationGraphState) -> dict[str, Any]:
        request = GenerationRequest.from_value(state["request"])
        reporter = ProgressReporter(progress_hook)
        await reporter.emit(
            ProgressStage.VALIDATING,
            message="正在校验出题参数",
            target=request.total_questions,
        )
        request.validate()
        quotas = allocate_document_quotas(request.total_questions, request.document_percentages)
        normalized_evidence = _evidence_map_dict(state["evidence_by_document"])
        normalized_history = _history_dict(list(state.get("historical_questions", ())))
        await reporter.emit(
            ProgressStage.VALIDATING,
            fraction=1,
            message="参数校验完成",
            target=request.total_questions,
            payload={"quotas": quotas},
        )
        return {
            "request": _request_dict(request),
            "evidence_by_document": normalized_evidence,
            "historical_questions": normalized_history,
            "quotas": quotas,
            "workflow_stage": "validated",
        }

    async def blueprint_node(state: GenerationGraphState) -> dict[str, Any]:
        request = GenerationRequest.from_value(state["request"])
        reporter = ProgressReporter(progress_hook)
        if await supervisor._is_cancelled(cancel_check):
            # Supervisor 会在下一节点生成标准的取消结果；这里绝不启动模型调用。
            return {
                "blueprint": BlueprintPlan(()).to_dict(),
                "workflow_stage": "blueprint_skipped_for_cancel",
            }
        evidence_map = {
            document_id: [Evidence.from_value(item, document_id) for item in values]
            for document_id, values in state["evidence_by_document"].items()
        }
        flat_evidence = [
            item for document_id in state["quotas"] for item in evidence_map.get(document_id, ())
        ]
        await reporter.emit(
            ProgressStage.BLUEPRINT,
            message="正在理解重点资料并映射正文",
            target=request.total_questions,
        )
        blueprint = await supervisor.blueprint_agent.build(
            request.focus_materials,
            flat_evidence,
            target_count=request.total_questions,
            seed=request.random_seed,
        )
        await reporter.emit(
            ProgressStage.BLUEPRINT,
            fraction=1,
            message="考点蓝图已生成并写入检查点",
            target=request.total_questions,
            payload={
                "topics": len(blueprint.topics),
                "coverage_gaps": list(blueprint.coverage_gaps),
            },
        )
        return {"blueprint": blueprint.to_dict(), "workflow_stage": "blueprint_ready"}

    async def generate_review_node(state: GenerationGraphState) -> dict[str, Any]:
        result = await supervisor.run(
            state["request"],
            state["evidence_by_document"],
            historical_questions=state.get("historical_questions", ()),
            progress_hook=progress_hook,
            cancel_check=cancel_check,
            prebuilt_blueprint=state["blueprint"],
        )
        return {
            "generation_result": result.to_dict(),
            "workflow_stage": "generation_review_complete",
        }

    async def finalize_node(state: GenerationGraphState) -> dict[str, Any]:
        # 独立节点使完整试卷产出也成为一个检查点；数据库落库仍由 Celery 任务负责。
        return {
            "result": dict(state["generation_result"]),
            "workflow_stage": "finished",
        }

    builder = StateGraph(GenerationGraphState)
    builder.add_node("validate", validate_node)
    builder.add_node("blueprint", blueprint_node)
    builder.add_node("generate_review", generate_review_node)
    builder.add_node("finalize", finalize_node)
    builder.add_edge(START, "validate")
    builder.add_edge("validate", "blueprint")
    builder.add_edge("blueprint", "generate_review")
    builder.add_edge("generate_review", "finalize")
    builder.add_edge("finalize", END)
    return builder.compile(checkpointer=checkpointer)


async def _invoke_resumable(
    graph: Any,
    initial_state: GenerationGraphState,
    *,
    config: Mapping[str, Any] | None,
    checkpointer: Any,
) -> GenerationGraphState:
    if checkpointer is not None and config is not None:
        try:
            snapshot = await graph.aget_state(config)
            values = getattr(snapshot, "values", None) or {}
            pending_nodes = tuple(getattr(snapshot, "next", ()) or ())
            if values.get("result"):
                return values
            if values and pending_nodes:
                # None 表示沿当前检查点继续，而不是以新输入重新从 START 开一轮。
                return await graph.ainvoke(None, config=config)
        except (KeyError, LookupError, ValueError):
            # 尚无该 thread_id 的检查点，按首次运行处理。
            pass
    return await graph.ainvoke(initial_state, config=config)


async def run_generation_graph(
    supervisor: GenerationSupervisor,
    request: Any,
    evidence_by_document: Mapping[str, Sequence[Any]],
    *,
    historical_questions: Sequence[Any] = (),
    progress_hook: Any = None,
    cancel_check: Any = None,
    checkpointer: Any = None,
    thread_id: str | None = None,
) -> Mapping[str, Any]:
    graph = build_generation_graph(
        supervisor,
        progress_hook=progress_hook,
        cancel_check=cancel_check,
        checkpointer=checkpointer,
    )
    config = {"configurable": {"thread_id": thread_id}} if thread_id else None
    final = await _invoke_resumable(
        graph,
        {
            "request": _request_dict(request),
            "evidence_by_document": _evidence_map_dict(evidence_by_document),
            "historical_questions": _history_dict(list(historical_questions)),
            "workflow_stage": "queued",
        },
        config=config,
        checkpointer=checkpointer,
    )
    return final["result"]
