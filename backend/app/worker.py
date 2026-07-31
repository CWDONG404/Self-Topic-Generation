"""Celery Worker 入口；未安装 Celery 时仍允许服务模块与单元测试导入。"""

from __future__ import annotations

import os
from collections.abc import Callable
from functools import update_wrapper
from typing import Any

try:  # Celery 是生产依赖，但保持开发期优雅降级。
    from celery import Celery

    from app.core.config import settings

    broker = settings.celery_broker_url or "memory://"
    backend = settings.celery_result_backend or None
    celery_app = Celery("document_quiz", broker=broker, backend=backend, include=["app.tasks"])
    celery_app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="Asia/Shanghai",
        enable_utc=True,
        task_track_started=True,
        task_acks_late=True,
        worker_prefetch_multiplier=1,
        task_soft_time_limit=60 * 60,
        task_time_limit=65 * 60,
        broker_connection_retry_on_startup=True,
        task_always_eager=os.getenv("CELERY_TASK_ALWAYS_EAGER", "").casefold()
        in {"1", "true", "yes"},
        task_eager_propagates=True,
    )
except ImportError:  # pragma: no cover - only for minimal optional installations

    class _LocalTask:
        def __init__(self, function: Callable[..., Any], *, bind: bool) -> None:
            self.function = function
            self.bind = bind
            update_wrapper(self, function)

        def __call__(self, *args: Any, **kwargs: Any) -> Any:
            return (
                self.function(None, *args, **kwargs)
                if self.bind
                else self.function(*args, **kwargs)
            )

        def delay(self, *args: Any, **kwargs: Any) -> Any:
            return self(*args, **kwargs)

        def apply_async(
            self, args: tuple[Any, ...] = (), kwargs: dict[str, Any] | None = None, **_: Any
        ) -> Any:
            return self(*args, **(kwargs or {}))

    class _LocalCelery:
        def task(self, *args: Any, **options: Any) -> Any:
            def decorate(function: Callable[..., Any]) -> _LocalTask:
                return _LocalTask(function, bind=bool(options.get("bind")))

            if args and callable(args[0]):
                return decorate(args[0])
            return decorate

    celery_app = _LocalCelery()


# 常用部署命令兼容 ``celery -A app.worker:app worker``。
app = celery_app
