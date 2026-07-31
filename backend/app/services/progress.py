"""与存储无关的任务进度事件。"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class ProgressStage(StrEnum):
    QUEUED = "queued"
    VALIDATING = "validating"
    BLUEPRINT = "blueprint"
    RETRIEVING = "retrieving"
    GENERATING = "generating"
    REVIEWING = "reviewing"
    ASSEMBLING = "assembling"
    COMPLETED = "completed"
    PARTIAL = "partial"
    CANCELLED = "cancelled"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class JobProgressEvent:
    sequence: int
    stage: ProgressStage
    progress: float
    message: str
    accepted: int = 0
    target: int = 0
    generated: int = 0
    rejected: int = 0
    revised: int = 0
    current_document: str | None = None
    current_topic: str | None = None
    warning: str | None = None
    error: str | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["stage"] = self.stage.value
        return result


ProgressHook = Callable[[JobProgressEvent], Awaitable[None] | None]


class ProgressReporter:
    """产生序号递增、进度不回退的事件并转发给任意同步/异步 hook。"""

    _RANGES: dict[ProgressStage, tuple[float, float]] = {
        ProgressStage.QUEUED: (0, 0),
        ProgressStage.VALIDATING: (0, 5),
        ProgressStage.BLUEPRINT: (5, 15),
        ProgressStage.RETRIEVING: (15, 25),
        # 生成、审题和返修会按补题轮次交错执行，因此共享同一进度区间。
        ProgressStage.GENERATING: (25, 90),
        ProgressStage.REVIEWING: (25, 90),
        ProgressStage.ASSEMBLING: (90, 99),
        ProgressStage.COMPLETED: (100, 100),
        ProgressStage.PARTIAL: (100, 100),
        ProgressStage.CANCELLED: (100, 100),
        ProgressStage.FAILED: (100, 100),
    }

    def __init__(self, hook: ProgressHook | None = None) -> None:
        self._hook = hook
        self._sequence = 0
        self._progress = 0.0

    @property
    def progress(self) -> float:
        return self._progress

    async def emit(
        self,
        stage: ProgressStage,
        *,
        fraction: float = 0,
        message: str = "",
        **values: Any,
    ) -> JobProgressEvent:
        start, end = self._RANGES[stage]
        fraction = max(0.0, min(1.0, float(fraction)))
        calculated = start + ((end - start) * fraction)
        self._progress = max(self._progress, calculated)
        self._sequence += 1
        allowed = {
            "accepted",
            "target",
            "generated",
            "rejected",
            "revised",
            "current_document",
            "current_topic",
            "warning",
            "error",
            "payload",
        }
        event_values = {key: value for key, value in values.items() if key in allowed}
        event = JobProgressEvent(
            sequence=self._sequence,
            stage=stage,
            progress=round(self._progress, 2),
            message=message,
            **event_values,
        )
        if self._hook is not None:
            result = self._hook(event)
            if inspect.isawaitable(result):
                await result
        return event
