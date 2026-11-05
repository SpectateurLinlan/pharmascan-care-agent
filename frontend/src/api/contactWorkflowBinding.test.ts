import { afterEach, expect, it, vi } from 'vitest';
import { api } from './client';

vi.mock('./auth', () => ({ accessToken: vi.fn().mockResolvedValue(null) }));
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
it.each(['create', 'update', 'delete'])(
  'binds independent contact %s to the current task without changing native fields',
  async (method) => {
    const fetch = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({}) });
    vi.stubGlobal('fetch', fetch);
    const details = {
      name: 'DEMO contact',
      relationship: null,
      contact_type: 'email' as const,
      contact_value: 'demo@example.invalid',
      storage_consent: true as const,
    };
    const binding = { task_id: 'DEMO-task', expected_revision: 3 };
    if (method === 'create') await api.createCaregiver({ ...details, id: 'DEMO-contact' }, binding);
    else if (method === 'update') await api.updateCaregiver('DEMO-contact', details, binding);
    else await api.deleteCaregiver('DEMO-contact', binding);
    const [, options] = fetch.mock.calls[0]!;
    expect(options.headers['X-Assistant-Task']).toBe('DEMO-task');
    expect(options.headers['X-Assistant-Revision']).toBe('3');
    expect(options.headers['X-Patient-Confirmed']).toBe('true');
  },
);
