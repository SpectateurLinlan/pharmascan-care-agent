import { afterEach, expect, it, vi } from 'vitest';
import { workflowApi } from './assistantWorkflows';

vi.mock('./auth', () => ({ accessToken: vi.fn().mockResolvedValue(null) }));
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
it('separates preview-original storage from the current explicitly consented read', async () => {
  const fetch = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({}) });
  vi.stubGlobal('fetch', fetch);
  const file = new File(['DEMO label'], 'DEMO.png', { type: 'image/png' });
  await workflowApi.uploadPreviewOriginal('DEMO-task', 'DEMO-upload', file, 2);
  const [url, store] = fetch.mock.calls[0]!;
  expect(url).toContain('source_kind=source_preview_photo');
  expect(store.body).toBe(file);
  expect(store.headers['X-Stage2-Consent']).toBe('false');
  await workflowApi.previewSource('DEMO-task', file, 3, true, 'prescription');
  const [read, request] = fetch.mock.calls[1]!;
  expect(read).toContain('expected_revision=3');
  expect(read).toContain('ephemeral_source_kind=prescription');
  expect(request.body).toBe(file);
  expect(request.headers['X-Stage2-Consent']).toBe('true');
});
