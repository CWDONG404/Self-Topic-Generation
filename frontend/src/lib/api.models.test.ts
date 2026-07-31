import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from './api';

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('model profile role mapping', () => {
  it('maps frontend generator to backend author and maps the response back', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 201,
      json: async () => ({
        id: 'model-1',
        name: 'Test model',
        provider: 'openai_compatible',
        base_url: 'https://api.example.com/v1',
        model_name: 'test-model',
        capabilities: { structured_output: true, vision: false, embedding: false },
        default_roles: ['blueprint', 'author', 'reviewer'],
        enabled: true,
        is_default: false,
        has_api_key: true,
        created_at: '2026-07-31T00:00:00Z',
      }),
      text: vi.fn(),
    });
    vi.stubGlobal('fetch', fetchMock);

    const profile = await api.createModelProfile({
      name: 'Test model',
      default_roles: ['blueprint', 'generator', 'reviewer'],
    });

    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
      name: 'Test model',
      default_roles: ['blueprint', 'author', 'reviewer'],
    });
    expect(profile.default_roles).toEqual(['blueprint', 'generator', 'reviewer']);
  });
});
