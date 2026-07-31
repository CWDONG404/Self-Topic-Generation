"""视觉描述与向量检索的轻量编排工具。"""

from __future__ import annotations

import math
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from app.services.model_gateway import BaseModelGateway

VISUAL_ANALYSIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "description": {"type": "string"},
        "key_facts": {"type": "array", "items": {"type": "string"}},
        "question_worthy": {"type": "boolean"},
    },
    "required": ["description", "key_facts", "question_worthy"],
    "additionalProperties": False,
}


async def embed_batches(
    gateway: BaseModelGateway,
    texts: Sequence[str],
    *,
    batch_size: int = 32,
) -> list[list[float]]:
    result: list[list[float]] = []
    for start in range(0, len(texts), batch_size):
        batch = list(texts[start : start + batch_size])
        values = await gateway.embed_texts(batch)
        if len(values) != len(batch):
            raise ValueError("Embedding 返回数量与输入数量不一致")
        dimensions = {len(item) for item in values}
        if not dimensions or 0 in dimensions or len(dimensions) != 1:
            raise ValueError("Embedding 维度无效或不一致")
        result.extend(values)
    return result


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if not left or len(left) != len(right):
        return 0.0
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return numerator / (left_norm * right_norm)


def ranked_indices(
    query: Sequence[float], vectors: Sequence[Sequence[float]], *, limit: int
) -> list[int]:
    ranked = sorted(
        enumerate(vectors),
        key=lambda item: cosine_similarity(query, item[1]),
        reverse=True,
    )
    return [index for index, _ in ranked[: max(0, limit)]]


async def describe_image(
    gateway: BaseModelGateway,
    path: str | Path,
    *,
    media_type: str | None,
    seed: int,
) -> dict[str, Any]:
    image_path = Path(path)
    payload = await gateway.complete_vision_json(
        prompt=(
            "请只描述这张备考资料中的图表、流程、关系和明确文字。提取可由图像直接支持的关键事实，"
            "不要根据常识补充图外信息；若图片只是装饰，应将 question_worthy 设为 false。"
        ),
        image_bytes=image_path.read_bytes(),
        media_type=media_type or "image/png",
        schema=VISUAL_ANALYSIS_SCHEMA,
        seed=seed,
    )
    if not isinstance(payload.data, dict):
        raise ValueError("视觉模型没有返回对象")
    return dict(payload.data)

