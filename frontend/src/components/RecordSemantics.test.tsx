// @vitest-environment jsdom
import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor,within} from '@testing-library/react';
import {api,type RegimenHistoryItem} from '../api/client';
import {regimenLabel} from '../regimenPresentation';
import {HistoryScreen,intakeLabel} from './HistoryScreen';
import {CareTasksScreen} from './CareTasksScreen';
import {HealthTrackingScreen} from './HealthTrackingScreen';

vi.mock('../api/client',()=>({ApiError:class extends Error{},api:{regimenHistory:vi.fn(),doseHistory:vi.fn(),careTasks:vi.fn(),createCareTask:vi.fn(),observations:vi.fn(),saveObservation:vi.fn()}}));
afterEach(()=>{cleanup();vi.resetAllMocks();});
const plan:RegimenHistoryItem={regimen_id:'DEMO-old',medication_id:'DEMO-med',display_name:'DEMO medicine 5 mg',version_no:1,state:'superseded',effective_from:'2026-10-01T23:00:00Z',effective_to:'2026-10-10T00:00:00Z',course_start_date:'2026-10-01',course_end_date:'2026-10-31',dose_amount:1,dose_unit:'tablet',food_instruction:null,is_prn:false,local_times:['08:00']};
it('labels plan changes by effective time, not a new treatment course or product strength',()=>{
 const label=regimenLabel(plan,key=>key,'en-SG','Asia/Singapore');
 expect(label).toContain('Dose: 1 tablet');expect(label).toContain('2 Oct 2026');expect(label).toContain('Previous plan');
 expect(label).not.toMatch(/version|Course|strength: 1/i);
 const changed={...plan,regimen_id:'DEMO-current',version_no:2,state:'active',effective_from:'2026-10-10T00:00:00Z'};
 expect(regimenLabel(changed,key=>key,'en-SG','Asia/Singapore')).not.toBe(label);
 expect(changed.course_start_date).toBe(plan.course_start_date);
});
it('keeps all four dose states distinct, without inferring a missed dose',()=>{
 const values=['reported_taken','reported_not_taken','unsure',null].map(intakeLabel);
 expect(new Set(values).size).toBe(4);expect(values[3]).toBe('This dose has no record of whether you took it yet.');
 expect(values[0]).toBe('You reported taking this dose');expect(values[1]).toBe('You reported not taking this dose');
});
it('selects the same stable plan IDs across versions and distinct course dates',async()=>{
 const plans=[plan,{...plan,regimen_id:'DEMO-current',state:'active',version_no:2,effective_from:'2026-10-10T00:00:00Z'},{...plan,regimen_id:'DEMO-other-course',course_start_date:'2026-08-01',course_end_date:'2026-08-30',effective_from:'2026-08-01T00:00:00Z',state:'ended'}];
 vi.mocked(api.regimenHistory).mockResolvedValue(plans);
 vi.mocked(api.doseHistory).mockImplementation(async id=>({item_count:1,note:'demo_only',entries:[{occurrence_id:`DEMO-${id}`,due_at:'2026-10-02T00:00:00Z',reported:false,intake_status:null,visual_status:null}]}));
 render(<HistoryScreen/>);await screen.findByText('This dose has no record of whether you took it yet.');
 const select=screen.getByLabelText('Medication plan');expect(select.querySelectorAll('option')).toHaveLength(3);
 for(const row of plans){fireEvent.change(select,{target:{value:row.regimen_id}});await waitFor(()=>expect(api.doseHistory).toHaveBeenLastCalledWith(row.regimen_id));}
});
it('makes follow-up creation visible, cancellable and still confirmation gated',async()=>{
 vi.mocked(api.careTasks).mockResolvedValue([]);render(<CareTasksScreen regimens={[plan]}/>);
 await screen.findByText('No medication follow-ups recorded.');fireEvent.click(screen.getByRole('button',{name:'Add medication follow-up'}));
 expect(screen.getByLabelText('Follow-up title (required)').hasAttribute('required')).toBe(true);
 fireEvent.change(screen.getByLabelText('Follow-up title (required)'),{target:{value:'DEMO review'}});
 fireEvent.change(screen.getByLabelText('Date and time (required)'),{target:{value:'2026-10-20T08:00'}});
 fireEvent.click(screen.getByRole('button',{name:'Review follow-up'}));expect(api.createCareTask).not.toHaveBeenCalled();
 fireEvent.click(within(screen.getByRole('dialog')).getByRole('button',{name:'Cancel'}));
 fireEvent.click(screen.getByRole('button',{name:'Cancel'}));
 expect(screen.queryByLabelText('Follow-up title (required)')).toBeNull();
 expect(api.createCareTask).not.toHaveBeenCalled();
 vi.mocked(api.createCareTask).mockImplementation(async input=>({...input,patient_id:'DEMO-owner',status:'open',source:'patient_reported',version:1,history:[],created_at:'2026-10-17T00:00:00Z',updated_at:'2026-10-17T00:00:00Z',demo_only:true}));
 fireEvent.click(screen.getByRole('button',{name:'Add medication follow-up'}));
 fireEvent.change(screen.getByLabelText('Follow-up title (required)'),{target:{value:'DEMO review'}});
 fireEvent.change(screen.getByLabelText('Date and time (required)'),{target:{value:'2026-10-20T08:00'}});
 fireEvent.change(screen.getByLabelText('Related medication (optional)'),{target:{value:plan.regimen_id}});
 fireEvent.click(screen.getByRole('button',{name:'Review follow-up'}));
 expect(api.createCareTask).not.toHaveBeenCalled();
 fireEvent.click(within(screen.getByRole('dialog')).getByRole('button',{name:'Confirm record'}));
 await waitFor(()=>expect(api.createCareTask).toHaveBeenCalledWith(expect.objectContaining({confirmed:true,regimen_id:plan.regimen_id,medication_id:plan.medication_id,due_at:new Date('2026-10-20T08:00').toISOString()})));
 await waitFor(()=>expect(screen.queryByRole('dialog')).toBeNull());
});
it('keeps the health form visible and offers a focusable empty-state action',async()=>{
 vi.mocked(api.observations).mockResolvedValue([]);render(<HealthTrackingScreen medications={[]}/>);
 fireEvent.click(await screen.findByRole('button',{name:'Record how you feel'}));
 expect(document.activeElement).toBe(screen.getByLabelText('Describe how you feel (required)'));
 expect(screen.getByLabelText('Severity (optional)').closest('details')).toBeNull();expect(api.saveObservation).not.toHaveBeenCalled();
});
