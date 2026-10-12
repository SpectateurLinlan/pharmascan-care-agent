/**
 * Typed client for the PharmaScan Care backend.
 *
 * The UI talks ONLY to our own backend over HTTPS JSON. It must never call
 * PostgreSQL, the Stage2 vision API or any external service directly
 * (docs/ARCHITECTURE.md section B).
 *
 * Every type here mirrors a real backend response schema. Nothing is invented:
 * if a field is not returned by the backend it is not declared.
 */

const CLIENT_STORAGE_KEY = 'pharmascan.client_id';

/** Stable error shape returned by the backend's domain error handler. */
export interface ApiErrorBody {
  code: string;
  message: string;
  rule_id: string | null;
}

export class ApiError extends Error {
  readonly code: string;
  readonly ruleId: string | null;
  readonly status: number;

  constructor(status: number, body: ApiErrorBody) {
    super(body.message);
    this.name = 'ApiError';
    this.status = status;
    this.code = body.code;
    this.ruleId = body.rule_id;
  }
}

/**
 * A stable per-browser-tab id. Used to scope the synthetic demo patient so a
 * reload resumes the same record. This is NOT authentication.
 */
export function clientId(): string {
  const existing = window.localStorage.getItem(CLIENT_STORAGE_KEY);
  if (existing) return existing;
  const generated =
    typeof crypto !== 'undefined' && 'randomUUID' in crypto
      ? crypto.randomUUID()
      : `client-${Date.now()}-${Math.floor(Math.random() * 1e9)}`;
  window.localStorage.setItem(CLIENT_STORAGE_KEY, generated);
  return generated;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
  });

  if (!response.ok) {
    let body: ApiErrorBody = {
      code: 'INTERNAL_ERROR',
      message: `Request failed with status ${response.status}`,
      rule_id: null,
    };
    try {
      const parsed = (await response.json()) as Partial<ApiErrorBody>;
      body = {
        code: parsed.code ?? body.code,
        message: parsed.message ?? body.message,
        rule_id: parsed.rule_id ?? null,
      };
    } catch {
      // Non-JSON error body: keep the generic message.
    }
    throw new ApiError(response.status, body);
  }
  return (await response.json()) as T;
}

function withClient(path: string, extra?: Record<string, string>): string {
  const params = new URLSearchParams({ client_id: clientId(), ...(extra ?? {}) });
  return `${path}?${params.toString()}`;
}

// --- response types (mirror backend schemas.py) -----------------------------

export interface HealthResponse {
  status: 'ok';
  service: string;
  database: 'simulated_in_memory' | 'postgres';
  llm: 'unavailable_deterministic_degraded';
  stage2_vision: 'simulated' | 'live';
}

export interface DemoStartResponse {
  patient_id: string;
  session_id: string;
  demo_only: true;
  seeded_medication_count: number;
  note: string;
}

export interface MedicationSummary {
  medication_id: string;
  regimen_id: string;
  display_name: string;
  is_prn: boolean;
  version_no: number;
  identity_status: string;
  source_backed: boolean;
}

export interface MedicationListResponse {
  item_count: number;
  medications: MedicationSummary[];
  note: string;
}

export interface DraftCreateResponse {
  medication_id: string;
  regimen_id: string;
  state: string;
  source_id: string;
  missing_instructions: string[];
  reviewable_field_ids: string[];
  note: string;
}

export interface ConfirmChallengeResponse {
  regimen_id: string;
  challenge_id: string;
  session_id: string;
  session_state: string;
  session_state_version: number;
  expires_at: string;
  summary: {
    medication_name: string;
    dose_amount: number | null;
    dose_unit: string | null;
    frequency: { kind: string; local_times: string[]; days_of_week: number[] } | null;
    is_prn: boolean;
    version_no: number;
    local_timezone: string;
  };
  note: string;
}

export interface ConfirmActivateResponse {
  regimen_id: string;
  state: string;
  superseded_regimen_ids: string[];
}

export interface DueDoseResponse {
  occurrence_id: string | null;
  regimen_id: string;
  medication_display_name: string;
  dose_description: string | null;
  due_at: string | null;
  is_prn: boolean;
  visual_status: string;
  ingestion_proven: false;
}

export interface SelfReportResponse {
  event_id: string | null;
  intake_status: string;
  visual_status: string;
  already_recorded: boolean;
  ingestion_proven: false;
  note: string;
}

export interface DoseHistoryEntry {
  occurrence_id: string | null;
  due_at: string | null;
  intake_status: string | null;
  visual_status: string | null;
  reported: boolean;
}

export interface DoseHistoryResponse {
  item_count: number;
  entries: DoseHistoryEntry[];
  note: string;
}

export interface ToolTrace {
  tool_name: string;
  status: string;
  error_code: string | null;
  requires_confirmation: boolean;
  clarification_question: string | null;
  payload: Record<string, unknown>;
}

export interface AgentMessageResponse {
  message: string;
  intent: string;
  session_id: string;
  session_state: string;
  requires_confirmation: boolean;
  /** Always present so the UI can label degraded mode honestly. */
  mode: string;
  tool_traces: ToolTrace[];
}

// --- client -----------------------------------------------------------------

export interface DraftInput {
  medication_name: string;
  dose_amount?: number | null;
  dose_unit?: string | null;
  frequency_kind?: 'daily' | 'weekly' | 'interval_hours' | null;
  frequency_local_times?: string[];
  frequency_days_of_week?: number[];
  frequency_every_hours?: number | null;
  is_prn?: boolean;
  route?: string | null;
  food_instruction?: string | null;
}

export const api = {
  health: () => request<HealthResponse>('/api/health'),

  startDemo: () =>
    request<DemoStartResponse>('/api/demo/start', {
      method: 'POST',
      body: JSON.stringify({ client_id: clientId() }),
    }),

  listMedications: () => request<MedicationListResponse>(withClient('/api/me/medications')),

  createDraft: (input: DraftInput) =>
    request<DraftCreateResponse>(withClient('/api/medications/drafts'), {
      method: 'POST',
      body: JSON.stringify(input),
    }),

  reviewDraft: (sourceId: string) =>
    request<{ reviewed_field_count: number; source_id: string; note: string }>(
      withClient(`/api/medications/drafts/${sourceId}/review`),
      { method: 'POST', body: JSON.stringify({ field_ids: null }) },
    ),

  requestChallenge: (regimenId: string, sessionId: string) =>
    request<ConfirmChallengeResponse>(
      withClient(`/api/medications/drafts/${regimenId}/challenge`, {
        session_id: sessionId,
      }),
      { method: 'POST', body: JSON.stringify({}) },
    ),

  activate: (payload: {
    regimen_id: string;
    challenge_id: string;
    session_id: string;
    session_state: string;
    session_state_version: number;
  }) =>
    request<ConfirmActivateResponse>(withClient('/api/medications/activate'), {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  dueDose: (regimenId: string) =>
    request<DueDoseResponse>(withClient('/api/doses/due', { regimen_id: regimenId })),

  report: (occurrenceId: string, payload: {
    regimen_id: string;
    intake_status: string;
    idempotency_key: string;
  }) =>
    request<SelfReportResponse>(withClient(`/api/doses/${occurrenceId}/report`), {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  doseHistory: (regimenId: string, days = 7) =>
    request<DoseHistoryResponse>(
      withClient('/api/me/dose-history', { regimen_id: regimenId, days: String(days) }),
    ),

  sendMessage: (payload: {
    text: string;
    session_id: string | null;
    client_turn_id: string;
    slots: Record<string, unknown>;
  }) =>
    request<AgentMessageResponse>(withClient('/api/agent/messages'), {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
};
