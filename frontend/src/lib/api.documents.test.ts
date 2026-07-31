import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from './api';

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('document API routes', () => {
  it('accepts the document-version response returned by the parse endpoint', async () => {
    const versionResponse = {
      id: 'version-2',
      version_number: 2,
      status: 'uploaded',
      progress: 0,
    };
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 202,
      json: async () => versionResponse,
      text: vi.fn(),
    });
    vi.stubGlobal('fetch', fetchMock);

    await expect(api.parseDocument('document/1')).resolves.toEqual(versionResponse);
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/documents/document%2F1/parse',
      expect.objectContaining({ method: 'POST' }),
    );
  });
});
