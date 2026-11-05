import { afterEach, expect, it, vi } from 'vitest';
import { api } from './client';

vi.mock('./auth', () => ({ accessToken: vi.fn().mockResolvedValue(null) }));
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it('adds task/revision and explicit patient confirmation to existing native media methods only when bound', async () => {
  const fetch = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({}) });
  vi.stubGlobal('fetch', fetch);
  const binding = { task_id: 'DEMO-task', expected_revision: 4 };
  const update = {
    expected_version: 1,
    title: 'DEMO',
    category: 'other' as const,
    description: '',
  };
  await api.updateLibraryPdf('DEMO-id', update, binding);
  await api.deleteLibraryPdf('DEMO-id', binding);
  await api.retireReference('DEMO-id', binding);
  await api.manageReference(
    'DEMO-id',
    { action: 'delete', expected_version: 1, confirmed: true },
    binding,
  );
  for (const [, request] of fetch.mock.calls) {
    expect(request.headers['X-Assistant-Task']).toBe(binding.task_id);
    expect(request.headers['X-Assistant-Revision']).toBe('4');
  }
  expect(fetch.mock.calls[0]![0]).toContain('confirmed=true');
  expect(fetch.mock.calls[2]![0]).toContain('confirmed=true');
  await api.updateLibraryPdf('DEMO-id', update);
  expect(fetch.mock.calls[4]![1].headers['X-Assistant-Task']).toBeUndefined();
  expect(fetch.mock.calls[4]![0]).not.toContain('confirmed=');
});
