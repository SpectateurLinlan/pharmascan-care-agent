// @vitest-environment jsdom
import {expect,it} from 'vitest';
import type {DoseHistoryEntry} from '../api/client';
import type {StockStatus} from '../api/care';
import {deriveObservations} from './MedicationDifficultiesPanel';

const entry=(over:Partial<DoseHistoryEntry>):DoseHistoryEntry=>({occurrence_id:'o',due_at:'2026-10-14T00:00:00Z',intake_status:null,visual_status:'not_checked',reported:false,...over});
const stock=(over:Partial<StockStatus>):StockStatus=>({medication_id:'m',unit:'tablet',last_confirmed_stock:10,last_confirmed_at:null,estimated_remaining:10,daily_requirement:1,estimated_days:10,low_stock:false,estimate_note:'demo',transactions:[],...over});

it('counts unreported scheduled doses without ever calling them missed or a barrier',()=>{
 const rows=deriveObservations([entry({}),entry({reported:true,intake_status:'reported_taken'}),entry({})],null,7);
 const noReport=rows.find(row=>row.kind==='no_report');
 expect(noReport?.count).toBe(2);
 expect(noReport?.suggestedCategory).toBeNull();
});

it('never derives a barrier category from supply alone',()=>{
 const rows=deriveObservations(null,stock({low_stock:true,estimated_days:2}),7);
 const low=rows.find(row=>row.kind==='low_supply');
 expect(low?.count).toBe(2);
 expect(low?.suggestedCategory).toBeNull();
});

it('suggests a category only when the patient’s own report is the evidence',()=>{
 const rows=deriveObservations([entry({reported:true,intake_status:'unsure'}),entry({reported:true,intake_status:'reported_not_taken'})],null,7);
 expect(rows.find(row=>row.kind==='unsure_reports')?.suggestedCategory).toBe('unsure_taken');
 expect(rows.find(row=>row.kind==='reported_not_taken')?.suggestedCategory).toBeNull();
});

it('shows nothing when there is nothing recorded',()=>{
 expect(deriveObservations([],stock({}),7)).toHaveLength(0);
 expect(deriveObservations(null,null,7)).toHaveLength(0);
});
