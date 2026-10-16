// @vitest-environment jsdom
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {api} from '../api/client';
import {CareReviewSheet} from './CareReviewSheet';
import {InventoryPanel} from './InventoryPanel';
import {CareTaskSummary} from './CareTasksScreen';
import {MedicationReviewScreen} from './MedicationReviewScreen';
import type {CareReview,StockStatus,MedicationCareReview} from '../api/care';
vi.mock('../api/client',()=>({ApiError:class extends Error{},api:{inventory:vi.fn(),recordStock:vi.fn(),recordBarrier:vi.fn(),createCareTask:vi.fn(),updateCareTask:vi.fn(),refreshFollowUps:vi.fn(),medicationCareReview:vi.fn()}}));
const stock:StockStatus={medication_id:'demo-med',unit:'tablet',last_confirmed_stock:3,last_confirmed_at:'2026-10-15T00:00:00Z',estimated_remaining:2,daily_requirement:1,estimated_days:2,low_stock:true,estimate_note:'DEMO estimate',transactions:[]};
const proposal:CareReview={action:'stock',medication_id:'demo-med',stock:{id:'demo-idempotency',kind:'count',quantity:3,unit:'tablet',low_threshold:7,note:'DEMO',confirmed:false}};
beforeEach(()=>vi.resetAllMocks());afterEach(()=>{cleanup();vi.restoreAllMocks();});
it('keeps absent schedule unknown and names stock and provenance in the actual export',async()=>{
 const at='2026-10-16T00:00:00Z';const report:MedicationCareReview={generated_at:at,timezone:'Asia/Singapore',observation_window_days:30,
  summary:{period:'month',window_start:'2026-10-01T00:00:00Z',window_end:at,generated_at:at,timezone:'Asia/Singapore',reported_taken:0,reported_not_taken:0,unsure:0,observations:[],questions:[],coverage_note:'DEMO stored occurrences only',medications:[{medication_id:'demo-med',regimen_id:'demo-regimen',name:'DEMO Metformin 500 mg',version:1,state:'pending_review',is_prn:false,dose_amount:null,dose_unit:null,food_instruction:null,course_start:null,course_end:null,local_times:[],recorded_occurrences:0,without_report:0}]},
  source_records:[{name:'DEMO Metformin 500 mg',regimen_id:'demo-regimen',version:1,state:'pending_review',source_document_id:'demo-source',source_type:'manual',review_status:'pending',patient_review_is_professional_verification:false}],trends:[],barriers:[],inventory:[stock],follow_ups:[],questions:[],adherence_denominator:'DEMO unrecorded is unknown',source_note:'DEMO patient report'};
 vi.mocked(api.medicationCareReview).mockResolvedValue(report);let exported:Blob|undefined;
 vi.spyOn(URL,'createObjectURL').mockImplementation(blob=>{if(blob instanceof Blob)exported=blob;return 'blob:DEMO';});vi.spyOn(URL,'revokeObjectURL').mockImplementation(()=>undefined);vi.spyOn(HTMLAnchorElement.prototype,'click').mockImplementation(()=>undefined);
 render(<MedicationReviewScreen/>);await screen.findAllByText(/DEMO Metformin 500 mg/);expect(screen.queryByText(/As needed/)).toBeNull();
 fireEvent.change(screen.getByLabelText('Your additional questions (included in export)'),{target:{value:'DEMO ask about supply'}});fireEvent.click(screen.getByRole('button',{name:'Export medication review'}));expect(exported).toBeDefined();
 const content=await new Promise<string>((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result));reader.onerror=()=>reject(reader.error);reader.readAsText(exported!);});
 expect(content).toContain('DEMO Metformin 500 mg: Estimated remaining: 2 tablet');expect(content).toContain('Source document: demo-source');expect(content).toContain('DEMO ask about supply');expect(api.recordStock).not.toHaveBeenCalled();
});
it('identifies the medicine linked to an automatic supply task',async()=>{
 vi.mocked(api.refreshFollowUps).mockResolvedValue([{id:'demo-task',patient_id:'demo-owner',medication_id:'demo-med',regimen_id:null,category:'refill',title:'Review medication supply',due_at:'2026-10-16T00:00:00Z',status:'open',notes:'DEMO',source:'stock_estimate',version:1,history:[],created_at:'2026-10-16T00:00:00Z',updated_at:'2026-10-16T00:00:00Z',demo_only:true}]);
 render(<CareTaskSummary medications={[{medication_id:'demo-med',display_name:'DEMO Metformin 500 mg'}]} onOpen={vi.fn()}/>);await screen.findByText(/DEMO Metformin 500 mg/);
});
it('opening and cancelling a proposed stock record performs no write',()=>{
 const cancel=vi.fn();render(<CareReviewSheet proposal={proposal} onCancel={cancel} onSaved={vi.fn()}/>);
 expect(api.recordStock).not.toHaveBeenCalled();fireEvent.click(screen.getByRole('button',{name:'Cancel'}));expect(cancel).toHaveBeenCalledOnce();expect(api.recordStock).not.toHaveBeenCalled();
});
it('requires an explicit human click and preserves the retry key after failure',async()=>{
 const saved=vi.fn();vi.mocked(api.recordStock).mockRejectedValueOnce(new Error('DEMO provider unavailable')).mockResolvedValue(stock);
 render(<CareReviewSheet proposal={proposal} onCancel={vi.fn()} onSaved={saved}/>);
 fireEvent.change(screen.getByLabelText('Quantity'),{target:{value:'4'}});fireEvent.click(screen.getByRole('button',{name:'Confirm record'}));await screen.findByRole('alert');expect(saved).not.toHaveBeenCalled();
 fireEvent.click(screen.getByRole('button',{name:'Confirm record'}));await waitFor(()=>expect(saved).toHaveBeenCalledOnce());
 expect(api.recordStock).toHaveBeenNthCalledWith(1,'demo-med',expect.objectContaining({id:'demo-idempotency',quantity:4,confirmed:true}));expect(api.recordStock).toHaveBeenNthCalledWith(2,'demo-med',expect.objectContaining({id:'demo-idempotency',quantity:4,confirmed:true}));
});
it('keeps unavailable stock distinct from an empty or zero stock',async()=>{
 vi.mocked(api.inventory).mockRejectedValue(new Error('DEMO unavailable'));render(<InventoryPanel medicationId="demo-med"/>);await screen.findByRole('alert');expect(screen.queryByText('0 tablet')).toBeNull();expect(api.recordStock).not.toHaveBeenCalled();
});
it('renders estimated stock and a source-scoped ledger, never medicine strength as count',async()=>{
 vi.mocked(api.inventory).mockResolvedValue(stock);render(<InventoryPanel medicationId="demo-med"/>);await screen.findByText('Low stock: review your supply with your pharmacy.');expect(screen.getByText(/Unreported consumption is unknown/)).toBeTruthy();expect(screen.getByText('Estimated remaining')).toBeTruthy();expect(screen.queryByText('500 tablets')).toBeNull();
});
it('task summary reports unavailable reads and refreshes through the existing reminder tick',async()=>{
 vi.mocked(api.refreshFollowUps).mockRejectedValueOnce(new Error('DEMO unavailable')).mockResolvedValue([]);render(<CareTaskSummary onOpen={vi.fn()}/>);await screen.findByRole('alert');expect(screen.queryByText('No open medication follow-ups.')).toBeNull();window.dispatchEvent(new Event('pharmascan:reminder-refresh'));await screen.findByText('No open medication follow-ups.');expect(api.refreshFollowUps).toHaveBeenCalledTimes(2);
});
it('task confirmation is separate from a proposed appointment and cannot create a dose event',async()=>{
 const task={id:'demo-task',category:'medication_review' as const,title:'DEMO review',due_at:'2026-10-23T08:00:00Z',medication_id:null,regimen_id:null,notes:'DEMO patient-reported',confirmed:false};
 const saved=vi.fn();vi.mocked(api.createCareTask).mockResolvedValue({...task,patient_id:'demo-user',status:'open',source:'patient_reported',version:1,history:[],created_at:'2026-10-16T00:00:00Z',updated_at:'2026-10-16T00:00:00Z',demo_only:true});
 render(<CareReviewSheet proposal={{action:'task',task}} onCancel={vi.fn()} onSaved={saved}/>);expect(api.createCareTask).not.toHaveBeenCalled();fireEvent.click(screen.getByRole('button',{name:'Confirm record'}));await waitFor(()=>expect(saved).toHaveBeenCalledOnce());expect(api.createCareTask).toHaveBeenCalledWith({...task,confirmed:true});expect(api.recordStock).not.toHaveBeenCalled();
});
