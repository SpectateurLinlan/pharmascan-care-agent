import { afterEach, expect, it, vi } from 'vitest';
import { api } from './client';

vi.mock('./auth', () => ({ accessToken: vi.fn().mockResolvedValue(null) }));
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
it('binds a current Assistant calendar without changing the legacy query protocol', async () => {
  const fetch = vi
    .fn()
    .mockResolvedValue({ ok: true, status: 200, blob: async () => new Blob(['DEMO ICS']) });
  vi.stubGlobal('fetch', fetch);
  await api.reminderCalendar(
    { range: '90', include_medications: true, include_tasks: false },
    { task_id: 'DEMO-task', expected_revision: 3 },
  );
  const [url, options] = fetch.mock.calls[0]!;
  expect(url).toContain('range=90');
  expect(url).toContain('include_tasks=false');
  expect(options.headers['X-Assistant-Task']).toBe('DEMO-task');
  expect(options.headers['X-Assistant-Revision']).toBe('3');
});
