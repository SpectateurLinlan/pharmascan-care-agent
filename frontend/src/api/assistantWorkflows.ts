/** Closed workflow transport types. Business confirmation stays in existing UI. */
import { authenticatedRequest, authenticatedResponse } from './client';
import { abortable } from './abortable';
import type { api, AgentMessageResponse, MedicationKnowledge, SourcePreview } from './client';

export type SaveMode = 'allowed' | 'ephemeral';
export type StorageState = 'ephemeral' | 'saving' | 'saved' | 'save_failed' | 'cleanup_pending';
export type WorkflowState =
  | 'choose_method'
  | 'collecting'
  | 'validating'
  | 'ready_for_review'
  | 'awaiting_confirmation'
  | 'executing'
  | 'completed'
  | 'failed_recoverable'
  | 'suspended'
  | 'cancelled'
  | 'outcome_unknown';
export type JsonValue =
  string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue };

export interface ExplanationStep {
  operation_key: string;
  outcome:
    'success' | 'partial' | 'not_found' | 'not_attempted' | 'unavailable' | 'failed' | 'pending';
  source_name: string | null;
  source_refs: string[];
  reason_key: string | null;
  count: number | null;
}

export interface BusinessRef {
  kind:
    | 'medication'
    | 'regimen'
    | 'enrollment_task'
    | 'source'
    | 'dose_event'
    | 'dose_occurrence'
    | 'late_report'
    | 'care_review'
    | 'media_review'
    | 'reminder_review'
    | 'reminder_action'
    | 'observation'
    | 'stock'
    | 'barrier'
    | 'care_task'
    | 'contact'
    | 'file'
    | 'conversation'
    | 'feedback'
    | 'preference'
    | 'settings_review'
    | 'settings_action'
    | 'agent_session'
    | 'conversation_cleanup';
  id: string;
  version: number | null;
}

export type ReviewComponent =
  | 'existing_activation'
  | 'existing_source_review'
  | 'existing_self_report'
  | 'existing_late_report'
  | 'existing_care_review'
  | 'existing_observation_review'
  | 'existing_draft_delete'
  | 'existing_plan_end'
  | 'existing_media_management'
  | 'existing_preference_review'
  | 'existing_reminder_review'
  | 'existing_contact_review'
  | 'existing_feedback_review';

export type WorkflowRoute =
  | 'today'
  | 'medicines'
  | 'records'
  | 'me'
  | 'assistant'
  | 'care-tasks'
  | 'adherence-barriers'
  | 'medication-review'
  | 'check'
  | 'check-result'
  | 'label'
  | 'manual'
  | 'edit-medication'
  | 'medicine-history'
  | 'medication-inventory'
  | 'unfinished'
  | 'past-medicines'
  | 'gallery'
  | 'medicine-detail'
  | 'health-notes'
  | 'medication-records'
  | 'summary-week'
  | 'summary-month'
  | 'summary-course'
  | 'profile'
  | 'account'
  | 'caregivers'
  | 'settings'
  | 'reminder-settings'
  | 'language-settings'
  | 'accessibility'
  | 'privacy'
  | 'conversations'
  | 'about'
  | 'feedback'
  | 'help';

export type UIAction =
  | { kind: 'conversation'; action: 'new' | 'resume' | 'clear'; conversation_id: string | null }
  | {
      kind: 'choice';
      action_id: string;
      options: Array<{ value: string; label_key: string; label_text?: string | null }>;
    }
  | { kind: 'fields'; schema_id: string; field_names: string[] }
  | {
      kind: 'upload';
      action_id: 'source_image' | 'reference_image' | 'library_pdf';
      processing_consent_required: boolean;
    }
  | {
      kind: 'existing_review';
      component_key: ReviewComponent;
      owned_ref: BusinessRef;
      expected_version: number;
    }
  | { kind: 'resume_task'; owned_ref: BusinessRef; expected_version: number }
  | { kind: 'secure_account'; action: 'status' | 'login' | 'link' | 'password' | 'signout' }
  | {
      kind: 'download';
      capability_id: 'reminder.calendar.export' | 'library.pdf.download';
      owned_ref: BusinessRef | null;
    }
  | {
      kind: 'device';
      action: 'camera' | 'upload' | 'microphone' | 'notification_permission' | 'speech_playback';
    }
  | { kind: 'navigate'; route: WorkflowRoute };

export interface WorkflowView {
  input_fields?: Record<string, JsonValue> | null;
  workspace_id?: string | null;
  conversation_id?: string | null;
  cleanup_pending?: boolean;
  protected_originals?: boolean;
  task_id: string;
  revision: number;
  capability_id: string;
  state: WorkflowState;
  save_mode: SaveMode;
  storage_state: StorageState;
  prompt_key: string;
  visible_fields: Record<string, JsonValue>;
  missing_fields: string[];
  actions: UIAction[];
  explanations: ExplanationStep[];
  result_ref: BusinessRef | null;
}

export interface WorkflowEvent {
  event_id: string;
  expected_revision: number;
  kind:
    | 'provide_fields'
    | 'choose_method'
    | 'select_candidate'
    | 'review_source'
    | 'prepare_confirmation'
    | 'report_business_result'
    | 'retry'
    | 'resume'
    | 'pause'
    | 'cancel_save'
    | 'allow_save'
    | 'cancel_task';
  values: Record<string, JsonValue>;
}
export type WorkflowEventHandler = (event: WorkflowEvent) => void | Promise<WorkflowView | void>;

export interface EphemeralPayload {
  capability_id: string;
  fields: Record<string, JsonValue>;
}

export interface CapabilityView {
  id: string;
  version: 1;
  title_key: string;
  mode: 'read' | 'workflow' | 'patient_ui' | 'device_ui' | 'navigation';
  input_schema_id: string;
  adapter_key: string;
  required_services: string[];
  available: boolean;
  reason: string | null;
}

export interface WorkflowCapabilities {
  contract_version: 1;
  enabled: boolean;
  progress_enabled?: boolean;
  capabilities: CapabilityView[];
}
export type RunStatus = 'running' | 'cancelling' | 'completed' | 'cancelled' | 'failed';
export interface RunProgress {
  sequence: number;
  run_id: string;
  action_key: 'application' | 'model' | 'tool' | null;
  kind:
    | 'run_started'
    | 'step_started'
    | 'step_completed'
    | 'step_failed'
    | 'run_cancelling'
    | 'run_completed'
    | 'run_cancelled'
    | 'run_failed';
  status: RunStatus;
  reason_key?:
    | 'cancelled'
    | 'deadline_exceeded'
    | 'budget_exceeded'
    | 'execution_failed'
    | 'worker_interrupted'
    | null;
  duration_ms?: number | null;
}
export interface RunSnapshot {
  status: RunStatus;
  metadata: { run_id: string };
  events: RunProgress[];
}
export async function readWorkflowRun(id: string, signal?: AbortSignal): Promise<RunSnapshot> {
  const lifetime = new AbortController();
  const stop = () => lifetime.abort();
  signal?.addEventListener('abort', stop, { once: true });
  if (signal?.aborted) stop();
  const timer = setTimeout(stop, 45_000);
  let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
  const cancel = () => {
    void reader?.cancel().catch(() => {});
  };
  lifetime.signal.addEventListener('abort', cancel, { once: true });
  try {
    return await abortable(async () => {
      const response = await authenticatedResponse(
        `/api/agent/workflows/runs/${encodeURIComponent(id)}`,
        { method: 'GET', signal: lifetime.signal },
      );
      if (!response.body) throw new Error('Processing status is unavailable.');
      reader = response.body.getReader();
      const decoder = new TextDecoder();
      let body = '';
      let size = 0;
      while (true) {
        const { value, done } = await reader.read();
        if (lifetime.signal.aborted) throw new DOMException('Request aborted', 'AbortError');
        if (done) {
          body += decoder.decode();
          break;
        }
        size += value.byteLength;
        if (size > 65_536) throw new Error('Processing status is unavailable.');
        body += decoder.decode(value, { stream: true });
      }
      let result: RunSnapshot;
      try {
        result = JSON.parse(body) as RunSnapshot;
      } catch {
        throw new Error('Processing status is unavailable.');
      }
      if (
        result?.metadata?.run_id !== id ||
        !['running', 'cancelling', 'completed', 'cancelled', 'failed'].includes(result.status) ||
        !Array.isArray(result.events)
      )
        throw new Error('Processing status is unavailable.');
      return result;
    }, lifetime.signal);
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener('abort', stop);
    lifetime.signal.removeEventListener('abort', cancel);
    cancel();
    if (reader) {
      try {
        reader.releaseLock();
      } catch {
        /* The cancelled read releases asynchronously. */
      }
    }
  }
}
export const cancelWorkflowRun = (id: string) =>
  authenticatedRequest<RunSnapshot>(`/api/agent/workflows/runs/${encodeURIComponent(id)}/cancel`, {
    method: 'POST',
    body: '{}',
  });
export interface KnowledgeQueryResult extends MedicationKnowledge {
  explanations: ExplanationStep[];
}
export interface KnowledgeQueryRequest {
  expected_revision: number;
  candidate_id?: string;
  ephemeral?: EphemeralPayload;
}
export type WorkflowMessageRequest = Parameters<typeof api.sendMessage>[0] & {
  workspace_id: string;
  task_id?: string;
  expected_revision?: number;
  ephemeral?: EphemeralPayload;
  save_mode?: SaveMode;
};
export interface WorkflowMessageResponse {
  reply: AgentMessageResponse;
  workflow: WorkflowView | null;
  explanations: ExplanationStep[];
}
export type WorkflowSourceKind = 'pharmacy_label' | 'prescription' | 'package';
export interface OriginalView {
  id: string;
  task_id: string;
  original_checksum: string;
  content_type: 'image/png' | 'image/jpeg' | 'application/pdf';
  byte_size: number;
  state: 'reserved' | 'saved';
  extraction_status:
    'pending' | 'consent_required' | 'succeeded' | 'failed' | 'interrupted' | 'not_requested';
  reason: string | null;
  cleanup_pending: boolean;
}
export interface SourcePreviewResult {
  outcome: 'success' | 'unavailable' | 'rejected';
  preview: SourcePreview | null;
  reason: 'service_unavailable' | 'extraction_rejected' | null;
}
export interface ComparisonResult {
  intent: 'personal' | 'identify';
  decision: 'match' | 'unknown' | 'ambiguous' | 'conflict' | 'missing_reference' | 'unavailable';
  reason_key:
    | 'visual_reference_only'
    | 'no_reviewed_reference'
    | 'image_unclear'
    | 'plan_conflict'
    | 'missing_reference'
    | 'service_unavailable';
  selected_medication: string | null;
  candidates: ReadonlyArray<{ name: string; strength: string | null; market: 'US' }>;
  safe_to_take: false;
  ingestion_proven: false;
  count_reliable: false;
}
export interface OriginalResponse {
  attachment: OriginalView;
  workflow: WorkflowView;
}
export interface EphemeralImageResult {
  task_id: string;
  revision: number;
  capability_id: string;
  save_mode: 'ephemeral';
  storage_state: 'ephemeral';
  outcome: 'success' | 'failed';
  reason: string | null;
  preview: SourcePreview | null;
  fields?: Record<string, JsonValue> | null;
}
export interface CleanupItem {
  attachment_id: string;
  state: 'pending' | 'deleted' | 'protected' | 'failed';
  reason: string | null;
  writer_pending: boolean;
}
const root = '/api/agent/workflows';

function photoQuery(revision: number, kind: WorkflowSourceKind) {
  return new URLSearchParams({ expected_revision: String(revision), source_kind: kind });
}

export const workflowApi = {
  knowledge: (id: string, payload: KnowledgeQueryRequest) =>
    authenticatedRequest<KnowledgeQueryResult>(
      `${root}/tasks/${encodeURIComponent(id)}/knowledge`,
      { method: 'POST', body: JSON.stringify(payload) },
    ),
  resumeDraft: (id: string, revision: number) =>
    authenticatedRequest<WorkflowView>(`${root}/tasks/${encodeURIComponent(id)}/resume-draft`, {
      method: 'POST',
      body: JSON.stringify({ expected_revision: revision }),
    }),
  async capabilities(): Promise<WorkflowCapabilities> {
    const result = await authenticatedRequest<WorkflowCapabilities>(`${root}/capabilities`);
    return result.contract_version === 1 && Array.isArray(result.capabilities)
      ? result
      : { contract_version: 1, enabled: false, capabilities: [] };
  },
  sendMessage: (payload: WorkflowMessageRequest) =>
    authenticatedRequest<WorkflowMessageResponse>(`${root}/messages`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  start: (payload: {
    capability_id: string;
    workspace_id: string;
    conversation_id?: string | null;
    values: Record<string, JsonValue>;
    save_mode: SaveMode;
    client_event_id: string;
  }) =>
    authenticatedRequest<WorkflowView>(`${root}/tasks`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  list: (workspace?: string, includeEphemeral = false) => {
    const query = new URLSearchParams();
    if (workspace) query.set('workspace_id', workspace);
    if (includeEphemeral) query.set('include_ephemeral', 'true');
    return authenticatedRequest<WorkflowView[]>(`${root}/tasks${query.size ? '?' + query : ''}`);
  },
  view: (id: string) =>
    authenticatedRequest<WorkflowView>(`${root}/tasks/${encodeURIComponent(id)}`),
  event: (id: string, event: WorkflowEvent, ephemeral?: EphemeralPayload) =>
    authenticatedRequest<WorkflowView>(`${root}/tasks/${encodeURIComponent(id)}/events`, {
      method: 'POST',
      body: JSON.stringify({ ...event, ...(ephemeral ? { ephemeral } : {}) }),
    }),
  preview: (id: string, ephemeral: EphemeralPayload) =>
    authenticatedRequest<WorkflowView>(`${root}/tasks/${encodeURIComponent(id)}/preview`, {
      method: 'POST',
      body: JSON.stringify({ ephemeral }),
    }),
  originals: (id: string) =>
    authenticatedRequest<OriginalView[]>(`${root}/tasks/${encodeURIComponent(id)}/attachments`),
  originalBlob: (id: string, attachment: string) =>
    authenticatedResponse(
      `${root}/tasks/${encodeURIComponent(id)}/attachments/${encodeURIComponent(attachment)}`,
    ).then((response) => response.blob()),
  uploadOriginal: (
    id: string,
    upload: string,
    file: File,
    revision: number,
    kind: WorkflowSourceKind,
    consent: boolean,
  ) =>
    authenticatedRequest<OriginalResponse>(
      `${root}/tasks/${encodeURIComponent(id)}/attachments/${encodeURIComponent(upload)}?${photoQuery(revision, kind)}`,
      {
        method: 'PUT',
        headers: { 'Content-Type': file.type, 'X-Stage2-Consent': String(consent) },
        body: file,
      },
    ),
  uploadPdfOriginal: (id: string, upload: string, file: File, revision: number) =>
    authenticatedRequest<OriginalResponse>(
      `${root}/tasks/${encodeURIComponent(id)}/attachments/${encodeURIComponent(upload)}?${new URLSearchParams({ expected_revision: String(revision), source_kind: 'library_pdf' })}`,
      {
        method: 'PUT',
        headers: { 'Content-Type': 'application/pdf', 'X-Stage2-Consent': 'false' },
        body: file,
      },
    ),
  uploadPreviewOriginal: (id: string, upload: string, file: File, revision: number) =>
    authenticatedRequest<OriginalResponse>(
      `${root}/tasks/${encodeURIComponent(id)}/attachments/${encodeURIComponent(upload)}?${new URLSearchParams({ expected_revision: String(revision), source_kind: 'source_preview_photo' })}`,
      {
        method: 'PUT',
        headers: { 'Content-Type': file.type, 'X-Stage2-Consent': 'false' },
        body: file,
      },
    ),
  previewSource: (
    id: string,
    file: File,
    revision: number,
    consent: boolean,
    ephemeralKind?: WorkflowSourceKind,
  ) =>
    authenticatedRequest<SourcePreviewResult>(
      `${root}/tasks/${encodeURIComponent(id)}/source-preview?${new URLSearchParams({ expected_revision: String(revision), ...(ephemeralKind ? { ephemeral_source_kind: ephemeralKind } : {}) })}`,
      {
        method: 'POST',
        headers: { 'Content-Type': file.type, 'X-Stage2-Consent': String(consent) },
        body: file,
      },
    ),
  uploadComparisonOriginal: (id: string, upload: string, file: File, revision: number) =>
    authenticatedRequest<OriginalResponse>(
      `${root}/tasks/${encodeURIComponent(id)}/attachments/${encodeURIComponent(upload)}?${new URLSearchParams({ expected_revision: String(revision), source_kind: 'comparison_photo' })}`,
      {
        method: 'PUT',
        headers: { 'Content-Type': file.type, 'X-Stage2-Consent': 'false' },
        body: file,
      },
    ),
  compareImage: (
    id: string,
    file: File,
    revision: number,
    consent: boolean,
    ephemeral?: { intent: 'personal' | 'identify'; regimen_id: string | null },
  ) =>
    authenticatedRequest<ComparisonResult>(
      `${root}/tasks/${encodeURIComponent(id)}/compare?${new URLSearchParams({ expected_revision: String(revision), ...(ephemeral ? { ephemeral_intent: ephemeral.intent, ...(ephemeral.regimen_id ? { ephemeral_regimen_id: ephemeral.regimen_id } : {}) } : {}) })}`,
      {
        method: 'POST',
        headers: { 'Content-Type': file.type, 'X-Stage2-Consent': String(consent) },
        body: file,
      },
    ),
  uploadReferenceOriginal: (id: string, upload: string, file: File, revision: number) =>
    authenticatedRequest<OriginalResponse>(
      `${root}/tasks/${encodeURIComponent(id)}/attachments/${encodeURIComponent(upload)}?${new URLSearchParams({ expected_revision: String(revision), source_kind: 'reference_photo' })}`,
      {
        method: 'PUT',
        headers: { 'Content-Type': file.type, 'X-Stage2-Consent': 'false' },
        body: file,
      },
    ),
  previewImage: (
    id: string,
    event: string,
    file: File,
    revision: number,
    kind: WorkflowSourceKind,
    consent: boolean,
  ) =>
    authenticatedRequest<EphemeralImageResult>(
      `${root}/tasks/${encodeURIComponent(id)}/preview-image/${encodeURIComponent(event)}?${photoQuery(revision, kind)}`,
      {
        method: 'POST',
        headers: { 'Content-Type': file.type, 'X-Stage2-Consent': String(consent) },
        body: file,
      },
    ),
  recoverOriginal: (
    id: string,
    attachment: string,
    revision: number,
    event = crypto.randomUUID(),
  ) =>
    authenticatedRequest<OriginalResponse>(
      `${root}/tasks/${encodeURIComponent(id)}/attachments/${encodeURIComponent(attachment)}/recover`,
      { method: 'POST', body: JSON.stringify({ expected_revision: revision, event_id: event }) },
    ),
  previewOriginal: (
    id: string,
    attachment: string,
    revision: number,
    consent: boolean,
    event: string,
  ) =>
    authenticatedRequest<OriginalResponse>(
      `${root}/tasks/${encodeURIComponent(id)}/attachments/${encodeURIComponent(attachment)}/preview`,
      {
        method: 'POST',
        headers: { 'X-Stage2-Consent': String(consent) },
        body: JSON.stringify({ expected_revision: revision, event_id: event }),
      },
    ),
  retryOriginal: (id: string, attachment: string, file: File, revision: number, consent: boolean) =>
    authenticatedRequest<OriginalResponse>(
      `${root}/tasks/${encodeURIComponent(id)}/attachments/${encodeURIComponent(attachment)}/retry?expected_revision=${revision}`,
      {
        method: 'PUT',
        headers: { 'Content-Type': file.type, 'X-Stage2-Consent': String(consent) },
        body: file,
      },
    ),
  retryCleanup: (id: string) =>
    authenticatedRequest<CleanupItem[]>(`${root}/tasks/${encodeURIComponent(id)}/cleanup`, {
      method: 'POST',
      body: '{}',
    }),
};
