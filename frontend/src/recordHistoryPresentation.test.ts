import {expect,it} from 'vitest';
import type {RegimenHistoryItem,DoseHistoryEntry} from './api/client';
import {newestPlans,pastHistory} from './recordHistoryPresentation';
const plan=(id:string,effective:string|null,state='ended',version=1):RegimenHistoryItem=>({regimen_id:id,medication_id:'DEMO-med',display_name:'DEMO drug',effective_from:effective,effective_to:null,state,version_no:version,course_start_date:null,course_end_date:null,dose_amount:1,dose_unit:'tablet',is_prn:false,food_instruction:null,local_times:[]});
it('uses effective date then ID, independent of response order, lifecycle and version',()=>{
 const rows=[plan('DEMO-old','2026-09-01T00:00:00Z','active',99),plan('DEMO-b','2026-10-01T00:00:00Z'),plan('DEMO-a','2026-10-01T00:00:00Z'),plan('DEMO-unknown',null)];
 expect(newestPlans(rows).map(row=>row.regimen_id)).toEqual(['DEMO-a','DEMO-b','DEMO-old','DEMO-unknown']);
 expect(newestPlans([...rows].reverse())).toEqual(newestPlans(rows));expect(rows[0]?.regimen_id).toBe('DEMO-old');
});
const row=(id:string,due:string|null,event:string|null):DoseHistoryEntry=>({occurrence_id:id,due_at:due,event_time:event,intake_status:'reported_taken',reported:true,visual_status:null});
it('orders scheduled associations and PRN reports, excludes future occurrences and ignores created_at',()=>{
 const now=Date.parse('2026-10-17T12:00:00Z');
 const rows=[{...row('DEMO-old','2026-10-16T15:59:00Z','2026-10-17T11:59:00Z'),created_at:'2026-10-17T12:00:00Z'},row('DEMO-new','2026-10-16T16:01:00Z','2026-10-16T16:02:00Z'),row('DEMO-prn',null,'2026-10-17T01:00:00Z'),row('DEMO-future','2026-10-17T13:00:00Z',null)];
 expect(pastHistory(rows,now).map(entry=>entry.occurrence_id)).toEqual(['DEMO-prn','DEMO-new','DEMO-old']);
});
