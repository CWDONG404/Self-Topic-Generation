from __future__ import annotations

import importlib
import logging
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)


def enqueue_task(task_name: str, *args: Any) -> bool:
    """尝试发送任务；调用方必须根据返回值完成失败状态收尾。"""

    if not settings.celery_broker_url:
        logger.error("未配置 CELERY_BROKER_URL，任务 %s 无法入队", task_name)
        return False
    try:
        tasks = importlib.import_module("app.tasks")
        task = getattr(tasks, task_name)
        task.delay(*args)
        return True
    except Exception:
        logger.exception("任务 %s 入队失败", task_name)
        return False
