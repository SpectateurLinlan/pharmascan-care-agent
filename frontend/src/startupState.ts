/** Independent read states; a failed or unknown catalogue is never empty. */
import type {DemoStartResponse,HealthResponse,MedicationListResponse,PatientPreferences,RegimenHistoryItem} from './api/client';

export type LoadState<T> = {status:'idle'|'loading'|'ready'|'error';data?:T;error?:unknown};
export interface StartupState {
 identity:LoadState<string>;
 preferences:LoadState<PatientPreferences>;
 active:LoadState<MedicationListResponse>;
 regimens:LoadState<RegimenHistoryItem[]>;
 session:LoadState<DemoStartResponse>;
 health:LoadState<HealthResponse>;
}
export function canRenderClinicalToday(state:StartupState):boolean {
 return state.identity.status==='ready'&&state.preferences.status==='ready'&&state.active.status==='ready'
  &&Boolean(state.identity.data)&&state.preferences.data?.patient_id===state.identity.data
  &&Boolean(state.active.data)
  &&state.health.status==='ready'&&state.health.data?.runtime_contract==='patient-ux-reminders-v1';
}
export function canClaimNoRegistrations(state:StartupState):boolean {
 return canRenderClinicalToday(state)&&state.active.data?.medications.length===0
  &&state.regimens.status==='ready'&&state.regimens.data?.length===0;
}
