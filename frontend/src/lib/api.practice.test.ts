import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from './api';

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('practice API routes', () => {
  it('saves one answer without issuing a follow-up session read', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 204,
      json: vi.fn(),
      text: vi.fn(),
    });
    vi.stubGlobal('fetch', fetchMock);

    await api.savePracticeAnswer('session-1', 'question-1', 'D');

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/practice-sessions/session-1/answers',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ question_id: 'question-1', selected_option: 'D' }),
      }),
    );
  });

  it('retries mistakes from the current submitted session', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        id: 'retry-session',
        paper_id: 'paper-1',
        mode: 'exam',
        status: 'in_progress',
        current_index: 0,
        score: null,
        correct_count: 0,
        total_count: 0,
        questions: [],
        answers: [],
        created_at: '2026-07-31T00:00:00Z',
        submitted_at: null,
      }),
      text: vi.fn(),
    });
    vi.stubGlobal('fetch', fetchMock);

    const result = await api.retryPracticeMistakes('session/with slash');

    expect(result.id).toBe('retry-session');
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/practice-sessions/session%2Fwith%20slash/retry-mistakes',
      expect.objectContaining({ method: 'POST' }),
    );
  });
});
