/** DEMO_ONLY typed HTTP fixtures; never used by the application runtime. */
import type {HistoryCatalogue,MedicationHistoryEntry,MedicationHistoryPage} from '../api/client';
export const historyCatalogue:HistoryCatalogue={
 medications:[{id:'DEMO-A',display_name:'DEMO Amlodipine',product_id:null,identity_status:'unverified'},{id:'DEMO-B',display_name:'DEMO Amlodipine',product_id:null,identity_status:'unverified'},{id:'DEMO-C',display_name:'DEMO Metformin',product_id:null,identity_status:'unverified'}],
 plans:[{id:'DEMO-old',medication_id:'DEMO-A',supersedes_id:null,effective_from:'2026-09-01T00:00:00Z',effective_to:'2026-10-01T00:00:00Z',state:'ended',dose_amount:1,dose_unit:'tablet',strength_text:'5 mg'},
 {id:'DEMO-new',medication_id:'DEMO-A',supersedes_id:'DEMO-old',effective_from:'2026-10-01T00:00:00Z',effective_to:null,state:'active',dose_amount:2,dose_unit:'tablet',strength_text:'5 mg'},
 {id:'DEMO-plan-B',medication_id:'DEMO-B',supersedes_id:null,effective_from:'2026-09-02T00:00:00Z',effective_to:null,state:'ended',dose_amount:1,dose_unit:'tablet',strength_text:'10 mg'}],
};
export function historyRecords(count:number):MedicationHistoryEntry[]{return Array.from({length:count},(_,i)=>({
 id:`scheduled:DEMO-${i}`,medication_id:'DEMO-A',regimen_id:'DEMO-new',display_name:'DEMO Amlodipine',sort_time:new Date(Date.UTC(2026,9,1,16,count-i)).toISOString(),due_at:new Date(Date.UTC(2026,9,1,16,count-i)).toISOString(),event_id:i%4===3?null:`DEMO-event-${i}`,event_time:i%4===3?null:'2026-10-02T01:00:00Z',submitted_at:i%4===3?null:'2026-10-03T01:00:00Z',reported:i%4!==3,intake_status:['reported_taken','reported_not_taken','unsure',null][i%4]!,kind:'scheduled',
}));}
export function historyPage(rows:MedicationHistoryEntry[],offset=0):MedicationHistoryPage{return {entries:rows.slice(offset,offset+5),next_cursor:rows.length>offset+5?`DEMO-page:${offset+5}`:null,window_start:'2026-09-01T00:00:00Z',window_end:'2026-10-17T00:00:00Z',as_of:'2026-10-17T00:00:00Z',scope:'stored_records_only',missing_plan_start:false};}
export function historyOffset(cursor?:string){return cursor?Number(cursor.split(':')[1]):0;}
