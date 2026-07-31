export interface QuotaInput {
  id: string;
  percentage: number;
}

export interface QuotaResult extends QuotaInput {
  count: number;
}

export function allocateByLargestRemainder(total: number, inputs: QuotaInput[]): QuotaResult[] {
  if (!Number.isInteger(total) || total < 0) throw new Error('总题数必须是非负整数');
  if (inputs.length === 0) return [];
  const percentageTotal = inputs.reduce((sum, item) => sum + item.percentage, 0);
  if (Math.abs(percentageTotal - 100) > 0.0001) throw new Error('文档比例之和必须为 100%');
  if (inputs.some((item) => item.percentage < 0)) throw new Error('文档比例不能为负数');

  const exact = inputs.map((item) => ({ ...item, exact: (item.percentage / 100) * total }));
  const base = exact.map((item) => ({ ...item, count: Math.floor(item.exact) }));
  let remaining = total - base.reduce((sum, item) => sum + item.count, 0);
  const order = base
    .map((item, index) => ({ index, remainder: item.exact - item.count }))
    .sort((a, b) => b.remainder - a.remainder || a.index - b.index);

  for (let i = 0; i < remaining; i += 1) base[order[i % order.length].index].count += 1;
  return base.map(({ id, percentage, count }) => ({ id, percentage, count }));
}
