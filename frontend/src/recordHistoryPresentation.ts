import type {DoseHistoryEntry,RegimenHistoryItem} from './api/client';

function timestamp(value:string|null|undefined):number {
 const parsed=Date.parse(value??'');return Number.isFinite(parsed)?parsed:Number.NEGATIVE_INFINITY;
}

/** Unknown effective dates sort last; equal dates use stable opaque IDs, never state/version. */
export function newestPlans(rows:RegimenHistoryItem[]):RegimenHistoryItem[]{
 return [...rows].sort((a,b)=>timestamp(b.effective_from)-timestamp(a.effective_from)||a.regimen_id.localeCompare(b.regimen_id));
}

/** Scheduled records belong to due_at; PRN reports use event_time. Neither proves ingestion. */
export function historyTime(entry:DoseHistoryEntry):string|null {
 return entry.due_at??entry.event_time??null;
}

export function pastHistory(rows:DoseHistoryEntry[],now:number):DoseHistoryEntry[]{
 return rows.filter(row=>timestamp(historyTime(row))<=now).sort((a,b)=>
  timestamp(historyTime(b))-timestamp(historyTime(a))||
  (a.occurrence_id??`${a.event_time??''}:${a.intake_status??''}`).localeCompare(b.occurrence_id??`${b.event_time??''}:${b.intake_status??''}`));
}
