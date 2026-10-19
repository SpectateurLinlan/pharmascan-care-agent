import type {RegimenHistoryItem} from './api/client';

export type HistoricalRegimenGroup={row:RegimenHistoryItem;versionCount:number};

/** Project confirmed version chains; preserve independent patient-medication registrations. */
export function regimenCourseGroups(regimens:RegimenHistoryItem[]):HistoricalRegimenGroup[]{
 const confirmed=regimens.filter(row=>row.state==='active'||row.state==='ended'||row.state==='superseded');
 const byId=new Map(confirmed.map(row=>[row.regimen_id,row]));
 const hasSuccessor=new Set(confirmed.filter(row=>validPredecessor(row,byId)).map(row=>row.supersedes_id!));
 return confirmed.filter(row=>!hasSuccessor.has(row.regimen_id)).map(row=>({row,versionCount:countVersions(row,byId)}));
}

function countVersions(row:RegimenHistoryItem,byId:Map<string,RegimenHistoryItem>){
 let count=1,current=row;const seen=new Set([row.regimen_id]);
 while(current.supersedes_id){const previous=byId.get(current.supersedes_id);if(!previous||!validPredecessor(current,byId)||seen.has(previous.regimen_id))break;seen.add(previous.regimen_id);count+=1;current=previous;}
 return count;
}

function validPredecessor(row:RegimenHistoryItem,byId:Map<string,RegimenHistoryItem>){
 const previous=row.supersedes_id?byId.get(row.supersedes_id):undefined;
 return !!previous&&previous.medication_id===row.medication_id&&previous.version_no<row.version_no;
}

export function plannedEndElapsed(row:{state:string;course_end_date:string|null},timeZone:string,now=new Date()){
 const today=new Intl.DateTimeFormat('en-CA',{timeZone,year:'numeric',month:'2-digit',day:'2-digit'}).format(now);
 return row.state==='active'&&!!row.course_end_date&&row.course_end_date<today;
}

export function plannedStartPending(row:{state:string;course_start_date:string|null},timeZone:string,now=new Date()){
 const today=new Intl.DateTimeFormat('en-CA',{timeZone,year:'numeric',month:'2-digit',day:'2-digit'}).format(now);
 return row.state==='active'&&!!row.course_start_date&&row.course_start_date>today;
}
