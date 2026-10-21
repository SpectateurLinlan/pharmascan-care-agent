import type {DoseBasis,DoseDisplay} from './dose';
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

import { accessToken,existingAccessToken } from './auth';
import { observeDiagnosticResponse } from './diagnosticContract';
import {beginApiTiming,emitApiTiming,errors,readJsonWithTiming} from './workflowPerformanceContract';

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

async function fetchResponse(path: string, init?: RequestInit,tokenProvider=accessToken,timing=import.meta.env.DEV?beginApiTiming(path,init?.method??'GET'):null): Promise<Response> {
  let token:string|null;
  try{token=await tokenProvider();}
  catch(caught){if(import.meta.env.DEV&&timing)emitApiTiming({...timing,kind:'response',end:performance.now(),auth_ms:performance.now()-timing.start,status:null,error:'SDK_UNAVAILABLE'});throw caught;}
  const authFinished=timing?performance.now():0;
  const controller=new AbortController();
  const abort=()=>controller.abort();
  if(init?.signal?.aborted)controller.abort();else init?.signal?.addEventListener('abort',abort,{once:true});
  const timer=setTimeout(abort,/agent\/messages|sources\/|evidence\/.*sources|visual|check-dose/.test(path)?120000:45000);
  let response:Response;
  try{response = await fetch(path, {
    cache:'no-store',
    ...init,
    signal:controller.signal,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
  });
  }catch(caught){if(import.meta.env.DEV&&timing)emitApiTiming({...timing,kind:'response',end:performance.now(),auth_ms:authFinished-timing.start,fetch_ms:performance.now()-authFinished,status:null,error:'NETWORK_FAILURE'});if(controller.signal.aborted&&!init?.signal?.aborted)throw new Error('Connection timed out. Please try again.');throw caught;}finally{clearTimeout(timer);init?.signal?.removeEventListener('abort',abort);}

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
    observeDiagnosticResponse(path,response.status,Boolean(token),body.message);
    if(import.meta.env.DEV&&timing){const dependency=/^Supabase rejected data operation \(HTTP (\d{3}); code ([A-Z0-9]{5}|PGRST\d{3}|unknown)\)$/.exec(body.message);emitApiTiming({...timing,kind:'response',end:performance.now(),auth_ms:authFinished-timing.start,fetch_ms:performance.now()-authFinished,status:response.status,error:errors.includes(body.code as typeof errors[number])?body.code:'other',...(dependency?{dependency_status:Number(dependency[1]),dependency_code:dependency[2]}:{})});}
    throw new ApiError(response.status, body);
  }
  observeDiagnosticResponse(path,response.status,Boolean(token));
  if(import.meta.env.DEV&&timing){const control=response.headers?.get('Cache-Control')??'';const cache_policy=['no-store','no-cache','private','public'].find(value=>control.split(',').some(part=>part.trim()===value))??'unspecified';emitApiTiming({...timing,kind:'response',end:performance.now(),auth_ms:authFinished-timing.start,fetch_ms:performance.now()-authFinished,status:response.status,cache_policy});}
  return response;
}

export class DiagnosticSessionUnavailable extends Error {}
/** Existing SDK session only: no anonymous bootstrap, arbitrary URLs or write methods. */
export function readDiagnosticCounts(path:'/api/me/medications'|'/api/me/regimens'):Promise<Response>{
 if(!['/api/me/medications','/api/me/regimens'].includes(path))throw new Error('Unsupported diagnostic endpoint');
 return fetchResponse(path,{method:'GET',redirect:'error'},async()=>{
  const token=await existingAccessToken();
  if(!token)throw new DiagnosticSessionUnavailable();
  return token;
 });
}

// Share overlapping reads only. Never retain settled patient data, share a
// caller's AbortSignal, or reuse a read started before a write.
const pendingReads=new Map<string,Promise<unknown>>();
let writeRevision=0;
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const method=(init?.method??'GET').toUpperCase();
  if(method!=='GET')writeRevision++;
  if(method!=='GET'||init?.signal||!/^\/api\/(me\/(dose-follow-ups|today-attention)|reminders\/alerts)(\?|$)/.test(path)){
    return readJsonWithTiming<T>(await fetchResponse(path, init),path);
  }
  const revision=writeRevision;
  const timing=import.meta.env.DEV?beginApiTiming(path,'GET'):null;
  let token:string|null;
  try{token=await accessToken();}catch(caught){if(import.meta.env.DEV&&timing)emitApiTiming({...timing,kind:'response',end:performance.now(),auth_ms:performance.now()-timing.start,status:null,error:'SDK_UNAVAILABLE'});throw caught;}
  const key=`${revision}\0${token??''}\0${path}`;
  const existing=pendingReads.get(key);
  if(existing){const auth_ms=timing?performance.now()-timing.start:0;try{return await existing as T;}finally{if(import.meta.env.DEV&&timing)emitApiTiming({...timing,kind:'response',end:performance.now(),auth_ms,status:null,shared:true});}}
  const pending=fetchResponse(path,init,async()=>token,timing).then(response=>readJsonWithTiming<T>(response,path));
  pendingReads.set(key,pending);
  try{return await pending;}finally{if(pendingReads.get(key)===pending)pendingReads.delete(key);}
}

export interface SpeechCapabilities { cloud_tts_allowed: boolean; available: boolean; provider: string; review_required: true; raw_audio_retained: false }
export interface TranscriptResponse { text: string; provider: string; request_id: string; confidence: null; review_required: true }
export interface RegimenHistoryItem { patient_edited?:boolean; frequency_rule?:MedicationSummary['frequency_rule'];regimen_id: string; supersedes_id?:string|null; display_name: string; version_no: number; state: string;
  effective_from: string | null; effective_to: string | null; medication_id:string;course_start_date:string|null;course_end_date:string|null;
  dose_amount:number|null;dose_unit:string|null;food_instruction:string|null;is_prn:boolean;local_times:string[] }
export interface PrintedEvidence {value:string;line:string}
export interface ImageRoute {image_type:'loose_pills'|'blister'|'package'|'printed'|'document'|'unchecked';checked:boolean;abstained:boolean;suggested_workflow:'pill_evidence'|'source_review'|'ask_patient';message:string}
export interface PrintedInstructions {text:string;line:string;dose:{amount:number;amount_max:number|null;unit:string|null}|null;times_per_day:number|null;every_hours:number|null;as_needed:boolean;times_of_day:string[];food:string|null;duration:string|null;max_per_day:string|null}
export interface SourcePreview { source_document_id: string; source_kind: string; provider: string; extraction_model: string;
  label_kind?:'dispensing'|'package'|'none'|null;dispensed_by?:PrintedEvidence|null;
  review_required: true; note: string; candidates: Array<{ product: { name: string; strength: string | null; source_lines: string[] };
    regimen_evidence: { directions: PrintedEvidence | null; instructions?:PrintedInstructions|null; indication?:PrintedEvidence|null;cautions?:Array<PrintedEvidence&{kind:string}>;supplied_quantity?:PrintedEvidence&{amount:number|null;unit:string|null}|null;date?:PrintedEvidence|null;expiry_date?:PrintedEvidence|null; dose_amount: null; frequency: null; administration_times: null; duration: null };
    list_comparison?:{status:'same_medicine'|'different_strength'|'contains_listed'|'not_on_list';message:string;medication_id:string|null}|null;
    review_status: 'extracted'; can_activate_regimen: false }> }

function withClient(path: string, extra?: Record<string, string>): string {
  const params = new URLSearchParams({ client_id: clientId(), ...(extra ?? {}) });
  return `${path}?${params.toString()}`;
}

// --- response types (mirror backend schemas.py) -----------------------------

export interface ConversationEntry {id:string;user_text:string;assistant_text:string;created_at:string}
export interface ConversationSummary {id:string;title:string;created_at:string;updated_at:string}
export interface ThreadMessage extends ConversationEntry {conversation_id:string;photo_attached:boolean}
export interface ThreadPage {conversation:ConversationSummary;entries:ThreadMessage[];next_before:string|null}
export interface NavigationContext {page:'medicines'|'medicine-detail'|'records';medication_id?:string|null;regimen_id?:string|null;display_name?:string|null}
export interface ConversationPage {entries:ConversationEntry[];next_before:string|null}
export interface PatientPreferences {
  conversation_history_enabled?:boolean;
  display_name?:string|null;
  patient_id:string;preferred_language:'en'|'zh';speech_locale:'en-SG'|'zh-CN';
  text_size:'standard'|'large';text_scale_percent?:number;voice_enabled:boolean;tts_autoplay:boolean;reminder_lead_minutes:number;reminders_enabled?:boolean;
  timezone:string;created_at:string;updated_at:string;
}
export interface CaregiverDetails {name:string;relationship:string|null;contact_type:'email'|'phone';contact_value:string;storage_consent:true}
export interface CaregiverContact extends CaregiverDetails {id:string;patient_id:string;verification_status:'pending';notifications_enabled:false;sharing_enabled:false;created_at:string;updated_at:string;demo_only:true}
export type PreferenceUpdate=Partial<Pick<PatientPreferences,'display_name'|'preferred_language'|'text_size'|'text_scale_percent'|'voice_enabled'|'tts_autoplay'|'conversation_history_enabled'|'reminder_lead_minutes'|'reminders_enabled'|'timezone'>>;

export interface Measurement {kind?:'note'|'blood_pressure'|'blood_glucose'|'weight'|'sleep'|'mood';value?:number|null;secondary_value?:number|null;unit?:'mmHg'|'mmol/L'|'mg/dL'|'kg'|'hours'|'score'|null}
export interface HealthObservation extends Measurement {id:string;patient_id:string;description:string;occurred_at:string;severity:'mild'|'moderate'|'severe'|null;notes:string|null;medication_id:string|null;source:'patient_reported';created_at:string;updated_at:string;demo_only:true}
export type ObservationInput=Pick<HealthObservation,'id'|'description'|'occurred_at'|'severity'|'notes'|'medication_id'> & Measurement & {confirmed:boolean};
export interface ReviewSummary {period:'week'|'month'|'course';window_start:string;window_end:string;generated_at:string;timezone:string;reported_taken:number;reported_not_taken:number;unsure:number;observations:HealthObservation[];questions:string[];coverage_note:string;
  medications:Array<{medication_id:string;regimen_id:string;name:string;version:number;state:string;is_prn:boolean;dose_amount:number|null;dose_unit:string|null;food_instruction:string|null;course_start:string|null;course_end:string|null;local_times:string[];recorded_occurrences:number;without_report:number}>}

export interface HealthResponse {multiple_care_reminders_enabled?:boolean;
  medication_library_files_enabled?: boolean;
  late_dose_reports_enabled?: boolean;
  care_task_followups_enabled?: boolean;
  runtime_contract?: string;
  status: 'ok';
  service: string;
  database: 'simulated_in_memory' | 'postgres' | 'supabase';
  llm: 'unavailable_deterministic_degraded' | 'gemini_configured';
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
  dose_basis?:DoseBasis|null;
  dose_amount?: number | null;
  dose_unit?: string | null;
  frequency_rule?: {kind:string;local_times:string[];days_of_week:number[];every_hours?:number|null;interval_anchor?:{local_date:string;local_time:string;time_source:'patient_entered'|'default_0800'}|null} | null;
  food_instruction?: string | null;
  course_start_date?: string | null;
  course_end_date?: string | null;
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
    food_instruction?: string|null;
    course_start_date?: string | null;
    course_end_date?: string | null;
    medication_name: string;
    dose_amount: number | null;
    dose_unit: string | null;
    frequency: { kind: string; local_times: string[]; days_of_week: number[];every_hours?:number|null;interval_anchor?:{local_date:string;local_time:string;time_source:'patient_entered'|'default_0800'}|null } | null;
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
  next_due_at?: string | null;
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

export interface ReportChallengeResponse {
  challenge_id: string | null;
  occurrence_id: string | null;
  regimen_id: string;
  session_id: string | null;
  session_state: string;
  session_state_version: number;
  expires_at: string | null;
  summary: {
    medication_display_name: string;
    dose_amount: number | null;
    dose_unit: string | null;
    regimen_version_no: number;
    occurrence_due_at: string | null;
    local_due_time: string | null;
    local_timezone: string;
    intake_status: string;
    intake_status_label: string;
    safety_notice: string;
    ingestion_proven: false;
    visual_status: string;
  };
  already_recorded: boolean;
  note: string;
}

export interface DoseHistoryEntry {
  occurrence_id: string | null;
  due_at: string | null;
  intake_status: string | null;
  visual_status: string | null;
  reported: boolean;
  event_time?: string | null;
}

export interface DoseHistoryResponse {
  item_count: number;
  entries: DoseHistoryEntry[];
  note: string;
}

export type MedicationHistoryRange='7'|'30'|'90'|'custom'|'all'|'plan';
export interface HistoryMedication {id:string;display_name:string;product_id:string|null;identity_status:string}
export interface HistoryPlan {patient_edited?:boolean;id:string;medication_id:string;supersedes_id:string|null;effective_from:string|null;effective_to:string|null;state:string;dose_amount:number|null;dose_unit:string|null;strength_text:string|null;dosage_form?:string|null;frequency?:{kind:string;local_times:string[];days_of_week:number[];every_hours:number|null}|null;is_prn?:boolean}
export interface HistoryCatalogue {medications:HistoryMedication[];plans:HistoryPlan[]}
export interface MedicationHistoryEntry {id:string;medication_id:string;regimen_id:string;display_name:string;sort_time:string;due_at:string|null;event_id:string|null;event_time:string|null;submitted_at:string|null;reported_late?:boolean;actual_administration_at?:string|null;intake_status:string|null;reported:boolean;kind:'scheduled'|'unscheduled'}
export interface MedicationHistoryPage {entries:MedicationHistoryEntry[];next_cursor:string|null;window_start:string|null;window_end:string;as_of:string;scope:'stored_records_only';missing_plan_start:boolean}
export interface MedicationHistoryFilters {medication_id?:string;medication_name?:string;regimen_id?:string;range_kind:MedicationHistoryRange;start?:string;end?:string}

export interface ToolTrace {
  tool_name: string;
  status: string;
  error_code: string | null;
  requires_confirmation: boolean;
  clarification_question: string | null;
  payload: Record<string, unknown>;
}

export interface AgentUsage {llm_user_turns:number;model_requests:number;limit:number;usage_date:string;next_reset_at:string;}

export interface MedicationSelection {choice_id:string;medication_id:string}
export interface MedicationChoice {id:string;question:'general_use'|'personal_instructions'|'personal_reason';prompt?:string;expires_at:string;options:Array<{medication_id:string;regimen_id:string;display_name:string;label:string}>}
export interface AgentMessageResponse {
  medication_choice?:MedicationChoice|null;
  conversation_id?:string|null;
  history_saved?:boolean|null;
  care_request?: import('./care').CareReview|null;
  health_note_request?:{description:string;requires_patient_review:true;urgent_help_advised?:boolean}|null;
  visual_check_request?: {regimen_id:string|null;requires_image:true;visual_status:"not_checked"}|null;
  usage?: AgentUsage | null;
  message: string;
  intent: string;
  session_id: string;
  session_state: string;
  requires_confirmation: boolean;
  /** Always present so the UI can label degraded mode honestly. */
  mode: string;
  tool_traces: ToolTrace[];
  pending_report?: { challenge_id: string; occurrence_id: string | null; regimen_id: string;
    idempotency_key: string; expires_at: string; summary: ReportChallengeResponse['summary'] } | null;
}

/** Client-relayed, unverified evidence. Not patient speech or owned record references. */
export interface ChatPhotoContext {
  image_type:ImageRoute['image_type'];workflow:ImageRoute['suggested_workflow'];checked:boolean;abstained:boolean;
  source_kind:'package'|'pharmacy_label'|'prescription';provider?:string;extraction_model?:string;
  products:Array<{name:string;strength:string|null;printed_lines:string[];printed_directions:string|null;printed_indication?:string|null;printed_cautions?:string[];instructions?:PrintedInstructions|null}>;
  visual?:{decision:VisualCheckResult['decision'];reason:string;candidates:VisualCheckResult['candidates'];count_reliable:boolean;ingestion_proven:false;safe_to_take_confirmed:false};
}

// --- client -----------------------------------------------------------------

export interface DraftInput {
  patient_edited?:boolean;
  supersedes_regimen_id?:string|null;
  course_start_date?: string | null;
  course_end_date?: string | null;
  extraction_evidence?: SourcePreview;
  medication_name: string;
  dose_basis?:DoseBasis|null;
  dose_amount?: number | null;
  dose_unit?: string | null;
  frequency_kind?: 'daily' | 'weekly' | 'interval' | 'interval_hours' | null;
  frequency_local_times?: string[];
  frequency_days_of_week?: number[];
  frequency_every_hours?: number | null;
  is_prn?: boolean;
  route?: string | null;
  food_instruction?: string | null;
}

export interface ReminderRecord { is_due?: boolean; occurrence_id: string; patient_id: string; remind_at: string; demo_only: true }
export interface PlannedReminder {occurrence_id:string;regimen_id:string;rule_id:string;medication_name:string;due_at:string;remind_at:string;slot:string}
export interface CalendarExportOptions {
  range:'30'|'90'|'remaining'|'custom';
  start_date?:string;
  end_date?:string;
  include_medications:boolean;
  include_tasks:boolean;
}
export interface PushSubscriptionInput {endpoint:string;keys:{p256dh:string;auth:string}}
export interface PushSubscriptionRecord {id:string;enabled:boolean}
export interface DoseReminderAlert {key:string;occurrence_id:string;regimen_id:string;medication_name:string;dose_amount:number|null;dose_unit:string|null;food_instruction:string|null;due_at:string;remind_at:string;expires_at?:string}

export interface VisualCheckResult { decision:'unknown'|'ambiguous'|'unavailable'; selected_medication:string|null; comparison_available:false; reason:string; candidates:Array<{external_catalogue_id:string;display_name:string|null;visual_similarity:number|null;market:'US';strength:string|null}>; count_reliable:boolean; ingestion_proven:false; safe_to_take_confirmed:false; next_action:string }

export interface EvidenceProduct {name:string;strength:string|null;dose_form:string|null;formulation:string|null;brand:string|null;manufacturer?:string|null;ingredients:string[];external_identifiers?:Record<string,string>;category:'unknown'|'POM'|'P'|'GSL'|'supplement';verification:'source_supplied'|'patient_reviewed'}
export interface EvidenceDraft {patient_edited?:boolean;medication_name:string;dose_amount:number|null;dose_unit:string|null;frequency_rule:{kind:string;local_times:string[];days_of_week:number[];every_hours:number|null}|null;is_prn:boolean;route?:string|null;food_instruction:string|null;course_start_date?:string|null;course_end_date?:string|null}
export interface EvidenceTask {id:string;medication_id:string;version:number;status:'pending_information'|'conflict'|'ready_for_review'|'draft_created';product:EvidenceProduct;product_missing?:string[];source_ids:string[];missing:string[];conflicts:string[];possible_duplicate_ids:string[];draft_regimen_id:string|null;suggested_regimen:EvidenceDraft|null}
export interface GalleryImage {id:string;medication_id:string;source_id?:string|null;image_kind:'loose_pill'|'package'|'blister'|'source';source_description:string;reviewed:boolean;eligibility:'associated'|'eligible'|'ineligible';eligibility_reason:string;created_at:string;metadata_version?:number;gallery_removed?:boolean;deleted_at?:string|null;cleanup_pending?:boolean}
export interface GalleryUploadResult {photo:GalleryImage;duplicate:boolean}
export interface GalleryEntry {evidence_task_id?:string|null;similar_name_records?:number;product_id?:string|null;source_document_count?:number;pdf_file_count?:number;file_count?:number;updated_at?:string|null;medication:{id:string;display_name:string;identity_status:string;product_id?:string|null};product:EvidenceProduct|null;status:'current'|'upcoming'|'historical'|'pending';regimens:Array<{id:string;state:string;version_no:number;effective_from?:string|null;effective_to?:string|null;course_start_date:string|null;course_end_date:string|null;dose_amount:number|null;dose_unit:string|null}>;images:GalleryImage[];eligible_count:number}
export interface MedicationLibrarySource {id:string;source_kind:'package'|'pharmacy_label'|'prescription'|'mock_import'|'user_manual';review_status:'extracted'|'user_reviewed'|'professional_verified'|'rejected';reviewed_at:string|null;recorded_at:string|null;extraction_evidence:SourcePreview|null;fields:Array<{id:string;field_name:string;field_value:unknown;review_status:string;reviewed_at:string|null}>;regimen_ids:string[];image_ids:string[]}
export interface MedicationLibraryFile {id:string;image_id:string|null;image_ids:string[];file_id?:string;name:string;original_filename?:string;format:'PNG'|'PDF';content_type:'image'|'pdf';photo_description:GalleryImage['image_kind']|null;purpose_tags:string[];created_at:string;eligibility:GalleryImage['eligibility'];eligibility_reason:string;sources:MedicationLibrarySource[];category?:'prescription'|'pharmacy_document'|'medication_instructions'|'other';description?:string;version?:number;byte_size?:number}
export interface MedicationLibraryPdf {id:string;patient_id:string;medication_id:string;original_filename:string;display_title:string;category:'prescription'|'pharmacy_document'|'medication_instructions'|'other';description:string;content_type:'application/pdf';byte_size:number;uploaded_at:string;version:number;deleted_at:string|null;cleanup_pending:boolean;demo_only:true}
export interface MedicationLibraryPdfUploadResult {file:MedicationLibraryPdf;duplicate:boolean}
export interface MedicationFiles {medication_id:string;file_management_available?:boolean;files:MedicationLibraryFile[];source_records:MedicationLibrarySource[];regimens:Array<{id:string;version_no:number;state:string;source_id:string|null;course_start_date:string|null;course_end_date:string|null;effective_from:string|null;effective_to:string|null}>}
export interface RecognitionEvidence {id:string;decision:'match'|'unknown'|'ambiguous'|'conflict'|'missing_reference'|'unavailable';reason:string;reference_ids:string[];outcome:{decision:string;medication_id:string|null;score:number|null;closest:{medication_id:string;name:string;score:number}|null}|null;safe_to_take:false;ingestion_proven:false}
export interface MedicationKnowledge {clarification_required:boolean;medication_id:string|null;regimen_id:string|null;question:'general_use'|'personal_instructions'|'personal_reason';medication_name:string|null;patient_safe_summary:string;general_knowledge:{status:'matched'|'no_reliable_match'|'unavailable';reason:string;match_scope:'US_label_product_family'|'US_label_ingredient';candidate_count:number;sources:Array<{source_name:string;market:'US';set_id:string;label_id:string;version:string;effective_time:string;retrieved_at:string;url:string;api_url:string;sections:Array<{field:string;text:string;truncated:boolean}>}>;use_statement:string|null;use_statement_zh:string|null;translation_status:'controlled_translation'|'original_english_only';personal_dosing_authority:false;regulatory_note:string}|null;personal_instructions:null;personal_indication:null}

export const api = {
  medicationKnowledge:(id:string,language:'en'|'zh')=>request<MedicationKnowledge>(withClient(`/api/me/medications/${encodeURIComponent(id)}/knowledge`,{language})),
  refreshFollowUps:()=>request<import('./care').CareTask[]>(withClient('/api/me/care-tasks/refresh'),{method:'POST'}),
  doseFollowUps:(includeReported=false)=>request<import('./doseFollowUps').DoseFollowUps>(withClient('/api/me/dose-follow-ups',{include_reported:String(includeReported)})),
  lateReportHistory:(id:string)=>request<import('./doseFollowUps').DoseReportAudit>(withClient(`/api/me/doses/${encodeURIComponent(id)}/late-reports`)),
  prepareLateReport:(id:string,values:import('./doseFollowUps').LateReportInput)=>request<import('./doseFollowUps').LateReportChallenge>(withClient(`/api/me/doses/${encodeURIComponent(id)}/late-report/challenge`),{method:'POST',body:JSON.stringify(values)}),
  confirmLateReport:(id:string,challenge:import('./doseFollowUps').LateReportChallenge)=>request<import('./doseFollowUps').LateReportRecord>(withClient(`/api/me/doses/${encodeURIComponent(id)}/late-report`),{method:'POST',body:JSON.stringify({challenge_id:challenge.challenge_id,report:challenge.proposed})}),
  inventory:(id:string)=>request<import('./care').StockStatus>(withClient(`/api/me/inventory/${encodeURIComponent(id)}`)),
  recordStock:(id:string,values:import('./care').StockInput)=>request<import('./care').StockStatus>(withClient(`/api/me/inventory/${encodeURIComponent(id)}`),{method:'POST',body:JSON.stringify(values)}),
  careTasks:(actionable=false)=>request<import('./care').CareTask[]>(withClient('/api/me/care-tasks',{actionable:String(actionable)})),
  createCareTask:(values:import('./care').CareTaskInput)=>request<import('./care').CareTask>(withClient('/api/me/care-tasks'),{method:'POST',body:JSON.stringify(values)}),
  updateCareTask:(id:string,values:import('./care').TaskUpdate)=>request<import('./care').CareTask>(withClient(`/api/me/care-tasks/${encodeURIComponent(id)}`),{method:'POST',body:JSON.stringify(values)}),
  barriers:()=>request<import('./care').Barrier[]>(withClient('/api/me/adherence-barriers')),
  recordBarrier:(values:import('./care').BarrierInput)=>request<import('./care').Barrier>(withClient('/api/me/adherence-barriers'),{method:'POST',body:JSON.stringify(values)}),
  medicationCareReview:(days:7|30)=>request<import('./care').MedicationCareReview>(withClient('/api/me/medication-review',{days:String(days)})),
  evidenceTasks:()=>request<EvidenceTask[]>(withClient('/api/evidence/tasks')),
  checkInput:(file:File)=>request<ImageRoute>(withClient('/api/sources/check-input'),{method:'POST',headers:{'Content-Type':file.type,'X-Stage2-Consent':'true','X-Demo-Only':'false'},body:file}),
  evidenceTask:(id:string)=>request<EvidenceTask>(withClient(`/api/evidence/tasks/${id}`)),
  evidenceSources:(id:string)=>request<Array<{id:string;source_kind:string;review_status:string;reviewed_at?:string|null;recorded_at?:string|null;provided_by?:'patient';extraction_evidence:SourcePreview|null}>>(withClient(`/api/evidence/tasks/${id}/sources`)),
  attachEvidence:(id:string,file:File,kind:'package'|'pharmacy_label'|'prescription',medicationId?:string,automaticallyRouted=false)=>request<EvidenceTask>(withClient(`/api/evidence/tasks/${id}/sources`,{source_kind:kind,automatically_routed:String(automaticallyRouted),...(medicationId?{medication_id:medicationId}:{})}),{method:'POST',headers:{'Content-Type':file.type,'X-Stage2-Consent':'true','X-Demo-Only':'false'},body:file}),
  reviewEvidence:(id:string,draft:EvidenceDraft,distinct_product_confirmed:boolean,options:{product_category?:EvidenceProduct['category'];replace_active_plan?:boolean}={})=>request<EvidenceTask>(withClient(`/api/evidence/tasks/${id}/review`),{method:'POST',body:JSON.stringify({...options,draft,patient_reviewed:true,distinct_product_confirmed})}),
  personalGallery:()=>request<GalleryEntry[]>(withClient('/api/evidence/gallery')),
  medicationFiles:(id:string)=>request<MedicationFiles>(withClient(`/api/evidence/gallery/${encodeURIComponent(id)}/files`)),
  retireReference:(id:string)=>request<GalleryImage>(withClient(`/api/evidence/images/${id}/retire`),{method:'POST',body:JSON.stringify({})}),
  manageReference:(id:string,values:{action:'edit'|'remove'|'delete';expected_version:number;image_kind?:GalleryImage['image_kind'];source_description?:string;confirmed?:boolean})=>request<GalleryImage>(withClient(`/api/evidence/images/${id}`),{method:'PATCH',body:JSON.stringify(values)}),
  referencePhoto:async(id:string)=>(await fetchResponse(withClient(`/api/evidence/images/${id}`))).blob(),
  uploadLibraryPdf:(medicationId:string,file:File,category:MedicationLibraryPdf['category'],description:string)=>request<MedicationLibraryPdfUploadResult>(withClient(`/api/evidence/gallery/${encodeURIComponent(medicationId)}/pdfs`,{filename:file.name,category,description}),{method:'POST',headers:{'Content-Type':'application/pdf'},body:file}),
  libraryPdf:async(id:string,disposition:'inline'|'attachment'='inline')=>(await fetchResponse(withClient(`/api/evidence/library-files/${encodeURIComponent(id)}`,{disposition}))).blob(),
  updateLibraryPdf:(id:string,values:{expected_version:number;title:string;category:MedicationLibraryPdf['category'];description:string})=>request<MedicationLibraryPdf>(withClient(`/api/evidence/library-files/${encodeURIComponent(id)}`),{method:'PATCH',body:JSON.stringify(values)}),
  deleteLibraryPdf:(id:string)=>request<{deleted:true}>(withClient(`/api/evidence/library-files/${encodeURIComponent(id)}`,{confirmed:'true'}),{method:'DELETE'}),
  addReference:(medicationId:string,file:File,kind:GalleryImage['image_kind'],source:string,reviewed:boolean,compare:boolean)=>request<GalleryUploadResult>(withClient(`/api/evidence/gallery/${medicationId}/images`,{image_kind:kind,source_description:source,reviewed:String(reviewed),for_comparison:String(compare)}),{method:'POST',headers:{'Content-Type':file.type,'X-Stage2-Consent':'true','X-Demo-Only':'false'},body:file}),
  checkPersonalDose:(file:File,regimenId:string|null)=>request<RecognitionEvidence>(withClient('/api/evidence/check-dose',regimenId?{regimen_id:regimenId}:{}),{method:'POST',headers:{'Content-Type':file.type,'X-Stage2-Consent':'true','X-Demo-Only':'false'},body:file}),
  conversationHistory:(before?:string)=>request<ConversationPage>(withClient('/api/agent/history',before?{before}:{})),
  conversations:(before?:string)=>request<{entries:ConversationSummary[];next_before:string|null}>(withClient('/api/agent/conversations',before?{before}:{})),
  conversation:(id:string,before?:string)=>request<ThreadPage>(withClient(`/api/agent/conversations/${encodeURIComponent(id)}`,before?{before}:{})),
  resumeConversation:(id:string)=>request<{conversation:ConversationSummary;session_id:string}>(withClient(`/api/agent/conversations/${encodeURIComponent(id)}/resume`),{method:'POST',body:'{}'}),
  navigationContext:(source:NavigationContext)=>request<NavigationContext>(withClient('/api/agent/navigation-context'),{method:'POST',body:JSON.stringify(source)}),
  clearConversationHistory:()=>request<{cleared:true}>(withClient('/api/agent/history'),{method:'DELETE',body:JSON.stringify({confirmed:true})}),
  doseDisplay:(basis:DoseBasis,units_per_dose:number,dose_unit:string)=>request<DoseDisplay>(withClient('/api/medications/dose-display'),{method:'POST',body:JSON.stringify({basis,units_per_dose,dose_unit})}),
  recentTurns:(sessionId:string)=>request<Array<{user:string;assistant:string}>>(withClient(`/api/agent/sessions/${sessionId}/recent-turns`)),
  observations:()=>request<HealthObservation[]>(withClient('/api/me/health-observations')),
  saveObservation:(record:ObservationInput)=>request<HealthObservation>(withClient('/api/me/health-observations'),{method:'PUT',body:JSON.stringify(record)}),
  deleteObservation:(id:string)=>request<{deleted:true}>(withClient(`/api/me/health-observations/${id}`),{method:'DELETE'}),
  reviewSummary:(period:'week'|'month'|'course',regimenId?:string)=>request<ReviewSummary>(withClient('/api/me/review-summary',{period,...(regimenId?{regimen_id:regimenId}:{})})),
  reminderPlan:()=>request<PlannedReminder[]>(withClient('/api/reminders/plan')),
  reminderCalendar:async(options?:CalendarExportOptions)=>{
    const query=options?{
      range:options.range,
      ...(options.start_date?{start_date:options.start_date}:{}),
      ...(options.end_date?{end_date:options.end_date}:{}),
      include_medications:String(options.include_medications),
      include_tasks:String(options.include_tasks),
    }:undefined;
    return (await fetchResponse(withClient('/api/reminders/calendar',query))).blob();
  },
  pushConfig:()=>request<{available:boolean;public_key:string|null;test_available?:boolean}>(withClient('/api/reminders/push/config')),
  currentPush:(value:PushSubscriptionInput)=>request<PushSubscriptionRecord|null>(withClient('/api/reminders/push/current'),{method:'POST',body:JSON.stringify(value)}),
  testPush:(id:string,requestId:string)=>request<{status:'sent'|'temporary'|'expired_subscription'|'provider_rejected'|'invalid_subscription'|'uncertain_delivery'}>(withClient('/api/reminders/push/test'),{method:'POST',body:JSON.stringify({subscription_id:id,request_id:requestId})}),
  pushSubscriptions:()=>request<PushSubscriptionRecord[]>(withClient('/api/reminders/push/subscriptions')),
  savePushSubscription:(value:PushSubscriptionInput)=>request<PushSubscriptionRecord>(withClient('/api/reminders/push/subscriptions'),{method:'POST',body:JSON.stringify(value)}),
  revokePushSubscription:async(id:string)=>{await fetchResponse(withClient(`/api/reminders/push/subscriptions/${encodeURIComponent(id)}`),{method:'DELETE'});},
  revokeCurrentPush:async(value:PushSubscriptionInput)=>{await fetchResponse(withClient('/api/reminders/push/unsubscribe'),{method:'POST',body:JSON.stringify(value)});},
  reminderAlerts:()=>request<DoseReminderAlert[]>(withClient('/api/reminders/alerts')),
  feedback:(payload:{id:string;category:'issue'|'suggestion';message:string})=>request<{id:string;status:'received';created_at:string}>(withClient('/api/feedback'),{method:'POST',body:JSON.stringify(payload)}),
  visualCheck: (image:File, regimenId:string|null) => request<VisualCheckResult>(withClient('/api/visual-check',regimenId ? {regimen_id:regimenId} : {}), {method:'POST',headers:{'Content-Type':image.type,'X-Stage2-Consent':'true','X-Demo-Only':'false'},body:image}),
  resumeDraft: (regimenId: string) => request<DraftCreateResponse>(withClient(`/api/medications/drafts/${regimenId}`)),
  reminders: () => request<ReminderRecord[]>(withClient('/api/reminders')),
  snoozeReminder: (occurrence_id: string, minutes: number) => request<ReminderRecord>(withClient('/api/reminders'), {method:'POST',body:JSON.stringify({occurrence_id,minutes})}),
  requestPrnReportChallenge: (payload: { regimen_id: string; intake_status: string; idempotency_key: string }) =>
    request<ReportChallengeResponse>(withClient('/api/prn/report/challenge'), { method: 'POST', body: JSON.stringify(payload) }),
  submitPrnReport: (payload: { regimen_id: string; intake_status: string; idempotency_key: string; challenge_id: string }) =>
    request<SelfReportResponse>(withClient('/api/prn/report'), { method: 'POST', body: JSON.stringify(payload) }),
  regimenHistory: () => request<RegimenHistoryItem[]>(withClient('/api/me/regimens')),
  historyCatalogue:()=>request<HistoryCatalogue>(withClient('/api/me/medication-history/catalogue')),
  medicationHistory:(filters:MedicationHistoryFilters,cursor?:string)=>request<MedicationHistoryPage>(withClient('/api/me/medication-history',{...filters,...(cursor?{cursor}:{})})),
  sourcePreview: (image: File, kind: 'package' | 'pharmacy_label' | 'prescription') => request<SourcePreview>(
    withClient('/api/sources/preview', { source_kind: kind }), {
      method: 'POST', headers: { 'Content-Type': image.type, 'X-Stage2-Consent': 'true', 'X-Demo-Only': 'false' }, body: image,
    }),
  speechCapabilities: () => request<SpeechCapabilities>(withClient('/api/speech/capabilities')),
  transcribe: (audio: Blob) => request<TranscriptResponse>(withClient('/api/speech/transcribe'), {
    method: 'POST', headers: { 'Content-Type': 'audio/wav', 'X-Speech-Consent': 'true' }, body: audio,
  }),
  synthesize: async (text: string, language: 'en' | 'zh' = 'en') => (await fetchResponse(withClient('/api/speech/synthesize'), {
    method: 'POST', body: JSON.stringify({ text, provider: "tencent", consent: true, language }),
  })).blob(),
  agentUsage:()=>request<AgentUsage>(withClient("/api/agent/usage")),
  preferences:()=>request<PatientPreferences>(withClient('/api/me/preferences')),
  caregivers:()=>request<CaregiverContact[]>(withClient('/api/me/caregivers')),
  createCaregiver:(details:CaregiverDetails&{id:string})=>request<CaregiverContact>(withClient('/api/me/caregivers'),{method:'POST',body:JSON.stringify(details)}),
  updateCaregiver:(id:string,details:CaregiverDetails)=>request<CaregiverContact>(withClient(`/api/me/caregivers/${encodeURIComponent(id)}`),{method:'PUT',body:JSON.stringify(details)}),
  deleteCaregiver:(id:string)=>request<{deleted:true}>(withClient(`/api/me/caregivers/${encodeURIComponent(id)}`),{method:'DELETE'}),
  updatePreferences:(changes:PreferenceUpdate)=>request<PatientPreferences>(withClient('/api/me/preferences'),{method:'PUT',body:JSON.stringify(changes)}),
  health: () => request<HealthResponse>('/api/health'),

  startDemo: () =>
    request<DemoStartResponse>('/api/demo/start', {
      method: 'POST',
      body: JSON.stringify({ client_id: clientId(),session_id:window.localStorage.getItem("pharmascan.agent-session") }),
    }),

  newConversation:()=>request<DemoStartResponse>('/api/demo/start',{method:'POST',body:JSON.stringify({client_id:clientId(),session_id:null})}),

  listMedications: () => request<MedicationListResponse>(withClient('/api/me/medications')),

  deleteDraft:(kind:'draft'|'source',id:string)=>request<{deleted:true;medication_deleted:boolean;cleanup_pending:boolean}>(withClient(`/api/medications/unfinished/${kind}/${encodeURIComponent(id)}`),{method:'DELETE',body:JSON.stringify({confirmed:true})}),
  endPlan:(regimenId:string)=>request<{regimen_id:string;state:string}>(withClient(`/api/medications/${encodeURIComponent(regimenId)}/end`),{method:'POST',body:JSON.stringify({confirmed:true})}),
  createDraft: (input: DraftInput, medicationId?:string) =>
    request<DraftCreateResponse>(withClient('/api/medications/drafts',medicationId?{medication_id:medicationId}:{}), {
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

  todayAttention: () => request<{as_of:string;local_date:string;timezone:string;plans:Array<{regimen_id:string;state:'pending'|'upcoming'|'unrecorded'|'recorded'|'as_needed'|'not_scheduled'|'unavailable';unrecorded_times:string[];next_due_at?:string|null}>}>(withClient('/api/me/today-attention')),
  dueDose: (regimenId: string, attentionOnly = false) =>
    request<DueDoseResponse>(withClient('/api/doses/due', { regimen_id: regimenId, ...(attentionOnly?{attention_only:'true'}:{}) })),

  requestReportChallenge: (occurrenceId: string, payload: {
    regimen_id: string;
    intake_status: string;
    idempotency_key: string;
  }) =>
    request<ReportChallengeResponse>(
      withClient(`/api/doses/${occurrenceId}/report/challenge`),
      { method: 'POST', body: JSON.stringify(payload) },
    ),

  submitReport: (occurrenceId: string, payload: {
    regimen_id: string;
    intake_status: string;
    idempotency_key: string;
    challenge_id: string;
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
    medication_selection?:MedicationSelection;
      conversation_id?:string|null;
      navigation_context?:NavigationContext;
    photo_context?:ChatPhotoContext;
    text: string;
    language?: 'en' | 'zh';
    session_id: string | null;
    client_turn_id: string;
    slots: Record<string, unknown>;
  }) =>
    request<AgentMessageResponse>(withClient('/api/agent/messages'), {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
};
