"""题量配额计算。

使用最大余数法（Hamilton method）把百分比转换为精确整数题数。相同余数按
调用方传入的顺序稳定分配，因而同一个请求总能得到相同结果。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_FLOOR, Decimal, InvalidOperation
from typing import TypeVar

KeyT = TypeVar("KeyT")


class QuotaError(ValueError):
    """配额参数不合法。"""


@dataclass(frozen=True, slots=True)
class QuotaShare:
    """单个分组的配额计算明细。"""

    weight: Decimal
    exact: Decimal
    allocated: int
    remainder: Decimal


def _decimal(value: int | float | str | Decimal) -> Decimal:
    try:
        number = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise QuotaError(f"无法识别的权重：{value!r}") from exc
    if not number.is_finite():
        raise QuotaError("权重必须是有限数字")
    return number


def largest_remainder_allocate(  # noqa: UP047 - 同时兼容本地 Python 3.11 测试环境
    total: int,
    weights: Mapping[KeyT, int | float | str | Decimal],
    *,
    expected_sum: int | float | str | Decimal | None = None,
    tolerance: Decimal = Decimal("0.000001"),
) -> dict[KeyT, int]:
    """将 ``total`` 按权重分成整数份，且结果之和严格等于 ``total``。

    ``expected_sum`` 用于百分比之类需要校验总和的场景。允许极小的浮点输入误差，
    但计算始终使用 :class:`~decimal.Decimal`，不会累计二进制浮点误差。
    """

    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        raise QuotaError("总题数必须是非负整数")
    if not weights:
        if total == 0:
            return {}
        raise QuotaError("至少需要一个配额分组")

    items = [(key, _decimal(value)) for key, value in weights.items()]
    if any(value < 0 for _, value in items):
        raise QuotaError("权重不能为负数")

    weight_sum = sum((value for _, value in items), Decimal(0))
    if weight_sum <= 0:
        if total == 0:
            return {key: 0 for key, _ in items}
        raise QuotaError("权重之和必须大于 0")

    if expected_sum is not None:
        expected = _decimal(expected_sum)
        if abs(weight_sum - expected) > tolerance:
            raise QuotaError(f"比例之和必须为 {expected}，当前为 {weight_sum}")

    exact: list[tuple[KeyT, Decimal, int, Decimal, int]] = []
    allocated = 0
    for index, (key, weight) in enumerate(items):
        share = Decimal(total) * weight / weight_sum
        floor_value = int(share.to_integral_value(rounding=ROUND_FLOOR))
        remainder = share - floor_value
        exact.append((key, share, floor_value, remainder, index))
        allocated += floor_value

    # Python 的排序稳定；显式加入原始下标可让行为更清晰，也适用于任意可哈希键。
    recipients = sorted(exact, key=lambda row: (-row[3], row[4]))
    result = {key: floor_value for key, _, floor_value, _, _ in exact}
    for key, *_ in recipients[: total - allocated]:
        result[key] += 1
    return result


def allocate_document_quotas(  # noqa: UP047 - 同时兼容本地 Python 3.11 测试环境
    total_questions: int,
    percentages: Mapping[KeyT, int | float | str | Decimal],
) -> dict[KeyT, int]:
    """按文档百分比计算题数；百分比之和必须为 100%。"""

    return largest_remainder_allocate(
        total_questions,
        percentages,
        expected_sum=Decimal(100),
    )


def allocation_details(  # noqa: UP047 - 同时兼容本地 Python 3.11 测试环境
    total: int,
    weights: Mapping[KeyT, int | float | str | Decimal],
) -> dict[KeyT, QuotaShare]:
    """返回用于界面解释配额的计算明细。"""

    allocation = largest_remainder_allocate(total, weights)
    converted = {key: _decimal(value) for key, value in weights.items()}
    weight_sum = sum(converted.values(), Decimal(0))
    return {
        key: QuotaShare(
            weight=weight,
            exact=(Decimal(total) * weight / weight_sum),
            allocated=allocation[key],
            remainder=(Decimal(total) * weight / weight_sum) % 1,
        )
        for key, weight in converted.items()
    }
