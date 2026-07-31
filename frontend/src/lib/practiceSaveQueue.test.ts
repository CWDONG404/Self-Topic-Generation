import { describe, expect, it, vi } from 'vitest';
import { createAnswerSaveQueue } from './practiceSaveQueue';

describe('createAnswerSaveQueue', () => {
  it('serializes rapid updates and keeps their order', async () => {
    let releaseFirst: (() => void) | undefined;
    const firstPending = new Promise<void>((resolve) => { releaseFirst = resolve; });
    const calls: string[] = [];
    const save = vi.fn(async (_questionId: string, answer: string) => {
      calls.push(answer);
      if (answer === 'A') await firstPending;
    });
    const queue = createAnswerSaveQueue(save);

    const first = queue.enqueue('question-1', 'A');
    const second = queue.enqueue('question-1', 'B');

    await vi.waitFor(() => expect(calls).toEqual(['A']));
    releaseFirst?.();
    await Promise.all([first, second]);
    expect(calls).toEqual(['A', 'B']);
  });

  it('waits for pending saves and persists the latest snapshot before resolving', async () => {
    const calls: Array<[string, string]> = [];
    const save = vi.fn(async (questionId: string, answer: string) => {
      calls.push([questionId, answer]);
    });
    const queue = createAnswerSaveQueue(save);

    void queue.enqueue('question-1', 'A');
    await queue.flush({ 'question-1': 'D', 'question-2': 'C' });

    expect(calls).toEqual([
      ['question-1', 'A'],
      ['question-1', 'D'],
      ['question-2', 'C'],
    ]);
  });

  it('recovers from an autosave failure when flushing the final snapshot', async () => {
    const save = vi.fn()
      .mockRejectedValueOnce(new Error('temporary failure'))
      .mockResolvedValue(undefined);
    const queue = createAnswerSaveQueue(save);

    await expect(queue.enqueue('question-1', 'A')).rejects.toThrow('temporary failure');
    await expect(queue.flush({ 'question-1': 'B' })).resolves.toBeUndefined();
    expect(save).toHaveBeenLastCalledWith('question-1', 'B');
  });
});
