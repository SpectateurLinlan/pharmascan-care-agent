import type {EvidenceTask,RegimenHistoryItem} from './api/client';

export type MedicationSetupEntry =
 | {kind:'source';id:string;name:string;conflicting:boolean}
 | {kind:'draft';id:string;name:string};

export function needsSourceReview(task:EvidenceTask){
 return task.status==='pending_information'||task.status==='conflict'||task.status==='ready_for_review';
}

/** The badge and destination consume the same patient-owned API snapshot. */
export function medicationSetupEntries(tasks:EvidenceTask[],versions:RegimenHistoryItem[]):MedicationSetupEntry[]{
 const pending=tasks.filter(needsSourceReview);
 const sourceDrafts=new Set(pending.map(task=>task.draft_regimen_id).filter(Boolean));
 return [
  ...pending.map(task=>({kind:'source' as const,id:task.id,name:[task.product.name,task.product.strength].filter(Boolean).join(' '),conflicting:task.conflicts.length>0})),
  ...versions.filter(row=>(row.state==='draft'||row.state==='pending_clarification')&&!sourceDrafts.has(row.regimen_id))
   .map(row=>({kind:'draft' as const,id:row.regimen_id,name:row.display_name})),
 ];
}
