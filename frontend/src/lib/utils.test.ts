import { describe, expect, it } from 'vitest';

import { clampProgress } from './utils';

describe('clampProgress', () => {
  it('treats backend progress as a percentage even between zero and one', () => {
    expect(clampProgress(0.5)).toBe(0.5);
    expect(clampProgress(1)).toBe(1);
  });

  it('clamps invalid or out-of-range values', () => {
    expect(clampProgress()).toBe(0);
    expect(clampProgress(Number.NaN)).toBe(0);
    expect(clampProgress(-5)).toBe(0);
    expect(clampProgress(120)).toBe(100);
  });
});
