import { describe, expect, it } from 'vitest';
import { allocateByLargestRemainder } from './quota';

describe('allocateByLargestRemainder', () => {
  it('保持总题量并按最大余数分配', () => {
    const result = allocateByLargestRemainder(50, [
      { id: 'a', percentage: 33 },
      { id: 'b', percentage: 33 },
      { id: 'c', percentage: 34 },
    ]);
    expect(result.map((item) => item.count)).toEqual([17, 16, 17]);
    expect(result.reduce((sum, item) => sum + item.count, 0)).toBe(50);
  });

  it('拒绝比例总和不为 100%', () => {
    expect(() => allocateByLargestRemainder(100, [{ id: 'a', percentage: 90 }])).toThrow('100%');
  });
});
