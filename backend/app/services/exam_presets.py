"""内置考试蓝图预设。

预设只负责确定性题量分配；题目事实仍必须来自用户选择的正文证据。
"""

from __future__ import annotations

CISE_V42_DISTRIBUTION: dict[str, int] = {
    "信息安全保障": 10,
    "网络安全监管": 8,
    "信息安全管理": 10,
    "业务连续性": 8,
    "安全工程与运营": 10,
    "安全评估": 8,
    "信息安全支撑技术": 10,
    "物理与网络通信安全": 12,
    "计算环境安全": 12,
    "软件安全开发": 12,
}

EXAM_PRESET_DISTRIBUTIONS: dict[str, dict[str, int]] = {
    "cise_v4_2": CISE_V42_DISTRIBUTION,
}

# 重点串讲材料中常见的简写，用于把章节证据归入标准知识域。
CISE_V42_TOPIC_ALIASES: dict[str, tuple[str, ...]] = {
    "信息安全支撑技术": ("信息安全支撑技术", "安全支撑技术"),
    "物理与网络通信安全": ("物理与网络通信安全", "物理与通信安全"),
}


def topic_aliases(name: str) -> tuple[str, ...]:
    return CISE_V42_TOPIC_ALIASES.get(name, (name,))
