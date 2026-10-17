/**
 * Tests for the typed API client's error handling.
 *
 * The important invariant: a refusal from the backend must surface as a typed
 * ApiError carrying the stable code. The UI must never be able to mistake a
 * refusal for a success.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, api } from '../api/client';
import { accessToken } from './auth';

vi.mock('./auth', () => ({ accessToken: vi.fn().mockResolvedValue(null) }));

function mockFetch(status: number, body: unknown) {
  return vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  });
}

describe('api client', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.mocked(accessToken).mockResolvedValue(null);
  });

  it('starts a new owned conversation without reusing the current session',async()=>{
    vi.mocked(accessToken).mockResolvedValue('DEMO.synthetic-token');
    const fetchMock=mockFetch(200,{patient_id:'DEMO-owner',session_id:'DEMO-new',demo_only:true,seeded_medication_count:0,note:'SIMULATED'});
    vi.stubGlobal('fetch',fetchMock);window.localStorage.setItem('pharmascan.agent-session','DEMO-old');
    expect((await api.newConversation()).session_id).toBe('DEMO-new');
    const init=fetchMock.mock.calls[0]![1] as RequestInit;
    expect(JSON.parse(init.body as string)).toMatchObject({session_id:null});
    expect(init.headers).toMatchObject({Authorization:'Bearer DEMO.synthetic-token'});
    expect(window.localStorage.getItem('pharmascan.agent-session')).toBe('DEMO-old');
  });

  it('parses a successful health response', async () => {
    vi.stubGlobal(
      'fetch',
      mockFetch(200, {
        status: 'ok',
        service: 'pharmascan-care-agent',
        database: 'simulated_in_memory',
        llm: 'unavailable_deterministic_degraded',
        stage2_vision: 'simulated',
      }),
    );

    const health = await api.health();
    expect(health.database).toBe('simulated_in_memory');
    expect(health.llm).toBe('unavailable_deterministic_degraded');
  });

  it('forwards the current authenticated access token to FastAPI', async () => {
    vi.mocked(accessToken).mockResolvedValue('synthetic-test-token');
    const fetchMock = mockFetch(200, { item_count: 0, medications: [] });
    vi.stubGlobal('fetch', fetchMock);
    await api.listMedications();
    expect(fetchMock.mock.calls[0]?.[1].headers.Authorization).toBe('Bearer synthetic-test-token');
  });

  it('refuses a business request when identity acquisition fails', async () => {
    vi.mocked(accessToken).mockRejectedValue(new Error('Anonymous sign-in unavailable'));
    const fetchMock = mockFetch(200, {});
    vi.stubGlobal('fetch', fetchMock);
    await expect(api.listMedications()).rejects.toThrow('Anonymous sign-in unavailable');
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('turns a domain refusal into a typed ApiError with the code', async () => {
    vi.stubGlobal(
      'fetch',
      mockFetch(409, {
        code: 'SOURCE_UNREVIEWED',
        message: 'Source must be reviewed before activation',
        rule_id: 'SOURCE_REVIEW_REQUIRED',
      }),
    );

    await expect(api.listMedications()).rejects.toBeInstanceOf(ApiError);

    try {
      await api.listMedications();
      throw new Error('expected the request to fail');
    } catch (error) {
      expect(error).toBeInstanceOf(ApiError);
      const apiError = error as ApiError;
      expect(apiError.code).toBe('SOURCE_UNREVIEWED');
      expect(apiError.ruleId).toBe('SOURCE_REVIEW_REQUIRED');
      expect(apiError.status).toBe(409);
    }
  });

  it('falls back to a generic error when the body is not JSON', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
        json: async () => {
          throw new Error('not json');
        },
      }),
    );

    try {
      await api.health();
      throw new Error('expected the request to fail');
    } catch (error) {
      const apiError = error as ApiError;
      expect(apiError.code).toBe('INTERNAL_ERROR');
      expect(apiError.status).toBe(500);
    }
  });

  it('sends the client id as a query parameter, never in the body', async () => {
    const fetchMock = mockFetch(200, { item_count: 0, medications: [], note: '' });
    vi.stubGlobal('fetch', fetchMock);

    await api.listMedications();

    const calledUrl = fetchMock.mock.calls[0]?.[0] as string;
    expect(calledUrl).toContain('client_id=');
  });

  it('keeps patient paths and encoded query values on the frontend origin', async () => {
    const fetchMock = mockFetch(200, {items: [], next_before: null});
    vi.stubGlobal('fetch', fetchMock);
    await api.conversationHistory('2026-10-16T20:00:00+08:00');
    const calledUrl = fetchMock.mock.calls[0]?.[0] as string;
    const url = new URL(calledUrl, 'https://medithread.vercel.app');
    expect(calledUrl.startsWith('/api/')).toBe(true);
    expect(url.origin).toBe('https://medithread.vercel.app');
    expect(url.pathname).toBe('/api/agent/history');
    expect(url.searchParams.get('before')).toBe('2026-10-16T20:00:00+08:00');
    expect(url.pathname).not.toContain('/api/api/');
  });

  it('posts a draft as JSON', async () => {
    const fetchMock = mockFetch(200, {
      medication_id: 'm',
      regimen_id: 'r',
      state: 'draft',
      source_id: 's',
      missing_instructions: [],
      reviewable_field_ids: [],
      note: '',
    });
    vi.stubGlobal('fetch', fetchMock);

    await api.createDraft({ medication_name: 'Amlodipine', dose_amount: 5 });

    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body as string)).toEqual({
      medication_name: 'Amlodipine',
      dose_amount: 5,
    });
  });
});
