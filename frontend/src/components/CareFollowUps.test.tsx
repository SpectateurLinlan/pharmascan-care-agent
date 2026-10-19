// @vitest-environment jsdom
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {act,cleanup,fireEvent,render,screen,waitFor,within} from '@testing-library/react';
import {api} from '../api/client';
import type {CareTask} from '../api/care';
import {patientInstant} from '../patientDateTime';
import {CareTaskForm} from './CareTaskForm';
import {CareTasksScreen,CareTaskSummary,taskView,todayTasks} from './CareTasksScreen';
import {LateDoseFollowUps} from './LateDoseFollowUps';
import {careTaskLocalDate,careTaskMonthDays,shiftCareTaskMonth,sortCareTasks} from '../careTaskCalendar';
import type {DoseFollowUp,LateReportChallenge} from '../api/doseFollowUps';

const now=Date.parse('2026-10-19T04:00:00Z');
const item:DoseFollowUp={occurrence_id:'demo-occ',regimen_id:'demo-plan',medication_id:'demo-med',medication_name:'DEMO medicine',due_at:'2026-10-19T00:00:00Z',dose_amount:1,dose_unit:'tablet',report_id:null,intake_status:null,actual_administration_at:null,recorded_at:null,reason:null,notes:''};
function task(id:string,due:string,status:CareTask['status']='open'):CareTask{return {id,title:`DEMO ${id}`,category:'medication_review',due_at:due,status,medication_id:null,regimen_id:null,notes:'DEMO',reminder_minutes:60,patient_id:'demo-owner',source:'patient_reported',version:1,history:[{id,status,due_at:due,notes:'DEMO',recorded_at:'2026-10-18T00:00:00Z'}],created_at:'2026-10-18T00:00:00Z',updated_at:'2026-10-18T00:00:00Z',demo_only:true};}
beforeEach(()=>{vi.spyOn(Date,'now').mockReturnValue(now);window.location.hash='care-tasks';});
afterEach(()=>{cleanup();vi.restoreAllMocks();});
it('uses patient IANA zone and rejects nonexistent/ambiguous DST local time',()=>{
 expect(patientInstant('2026-10-19','08:00','Asia/Singapore')).toBe('2026-10-19T00:00:00.000Z');
 expect(patientInstant('2026-10-19','08:00','America/New_York')).toBe('2026-10-19T12:00:00.000Z');
 expect(patientInstant('2026-03-08','02:30','America/New_York')).toBeNull();
 expect(patientInstant('2026-11-01','01:30','America/New_York')).toBeNull();
});
it('allows invalid submission, shows field errors and focuses the first invalid field',()=>{
 render(<CareTaskForm regimens={[]} onCancel={vi.fn()} onSaved={vi.fn()}/>);
 fireEvent.click(screen.getByRole('button',{name:'Review and save'}));
 expect(screen.getByLabelText('Title (required)')).toBe(document.activeElement);
 expect(screen.getAllByRole('alert')).toHaveLength(3);
});
it('requires explicit historical confirmation, never schedules a past reminder and saves after review',async()=>{
 const save=vi.spyOn(api,'createCareTask').mockResolvedValue(task('past','2026-10-18T00:00:00Z'));
 const saved=vi.fn();render(<CareTaskForm regimens={[]} onCancel={vi.fn()} onSaved={saved}/>);
 fireEvent.change(screen.getByLabelText('Title (required)'),{target:{value:'DEMO past'}});
 fireEvent.change(screen.getByLabelText('Date (required)'),{target:{value:'2026-10-18'}});
 fireEvent.change(screen.getByLabelText('Time (required)'),{target:{value:'08:00'}});
 fireEvent.click(screen.getByRole('button',{name:'Review and save'}));
 expect(screen.getByRole('alert').textContent).toContain('past');expect(save).not.toHaveBeenCalled();
 fireEvent.change(screen.getByLabelText('Advance reminder'),{target:{value:'none'}});
 fireEvent.click(screen.getByRole('button',{name:'Review and save'}));
 expect(save).not.toHaveBeenCalled();fireEvent.click(screen.getByRole('button',{name:'Confirm historical entry'}));
 fireEvent.click(screen.getByRole('button',{name:'Confirm and save'}));
 await waitFor(()=>expect(saved).toHaveBeenCalledOnce());
 expect(save).toHaveBeenCalledWith(expect.objectContaining({due_at:'2026-10-18T00:00:00.000Z',reminder_minutes:null,historical_confirmed:true,confirmed:true}));
});
it('filters lifecycle views and opens a readable detail instead of inline edit forms',async()=>{
 const rows=[task('future','2026-10-20T00:00:00Z'),task('overdue','2026-10-18T00:00:00Z'),task('done','2026-10-18T00:00:00Z','completed')];
 vi.spyOn(api,'careTasks').mockResolvedValue(rows);render(<CareTasksScreen regimens={[]}/>);
 await screen.findByRole('grid',{name:/October 2026/});fireEvent.click(screen.getByRole('button',{name:'List'}));expect(screen.getByRole('button',{name:/DEMO future/})).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'Overdue'}));fireEvent.click(screen.getByRole('button',{name:/DEMO overdue/}));
 const dialog=screen.getByRole('dialog',{name:'Follow-up details'});
 expect(within(dialog).getByText('Task created')).toBeTruthy();expect(within(dialog).queryByText('Reminder disabled')).toBeNull();expect(within(dialog).queryByRole('textbox')).toBeNull();
 expect(window.location.hash).toContain('task=overdue');
 expect(taskView(rows[1]!,now)).toBe('overdue');expect(todayTasks(rows,now).map(row=>row.id)).toEqual(['future','overdue']);
});
it('uses independent calendar/list and status filters over the same task rows',async()=>{
 const rows=[task('late','2026-10-19T02:00:00Z'),task('future','2026-10-19T05:00:00Z'),task('done','2026-10-19T03:00:00Z','completed')];
 vi.spyOn(api,'careTasks').mockResolvedValue(rows);render(<CareTasksScreen regimens={[]}/>);
 await screen.findByRole('grid',{name:/October 2026/});
 const today=(count:number)=>screen.getByRole('gridcell',{name:new RegExp(`19 October 2026, ${count} Care Tasks`)});expect(today(3).querySelectorAll('.care-calendar__marker')).toHaveLength(3);
 fireEvent.click(today(3));fireEvent.click(screen.getByRole('button',{name:/DEMO late/}));expect(screen.getByRole('dialog',{name:'Follow-up details'})).toBeTruthy();fireEvent.click(screen.getByRole('button',{name:'Close'}));
 fireEvent.click(screen.getByRole('button',{name:'Next month'}));expect(screen.getByRole('heading',{name:'November 2026'})).toBeTruthy();fireEvent.click(screen.getByRole('button',{name:'Today'}));expect(screen.getByRole('heading',{name:'October 2026'})).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'Completed'}));expect(today(1).querySelectorAll('.care-calendar__marker')).toHaveLength(1);
 fireEvent.click(screen.getByRole('button',{name:'List'}));expect(screen.getByRole('button',{name:/DEMO done/})).toBeTruthy();expect(screen.queryByRole('button',{name:/DEMO late/})).toBeNull();expect(screen.queryByRole('button',{name:/DEMO future/})).toBeNull();
 fireEvent.click(screen.getByRole('button',{name:'All'}));
 const groups=Array.from(document.querySelectorAll('.care-list-view h3')).map(node=>node.textContent?.trim().split(' ')[0]);expect(groups).toEqual(['Overdue','Pending','Completed']);
});
it('opens the existing Add Follow-up form directly and preselects today from the patient zone',async()=>{
 const open=vi.fn();vi.spyOn(api,'refreshFollowUps').mockResolvedValue([]);render(<CareTaskSummary onOpen={open}/>);
 await screen.findByText('No pending medication follow-ups.');
 fireEvent.click(screen.getByRole('button',{name:/Add Follow-up/}));
 const dialog=screen.getByRole('dialog',{name:'New medication follow-up'});expect(within(dialog).getByLabelText('Date (required)')).toHaveProperty('value','2026-10-19');expect(open).not.toHaveBeenCalled();
});
it('Today summary is bounded, pending-first, excludes completed and opens the selected task',async()=>{
 const rows=[task('late','2026-10-18T00:00:00Z'),task('done','2026-10-18T00:00:00Z','completed'),...['20','21','22','23'].map(day=>task(day,`2026-10-${day}T00:00:00Z`))];
 vi.spyOn(api,'refreshFollowUps').mockResolvedValue(rows);const open=vi.fn();render(<CareTaskSummary onOpen={open}/>);
 await screen.findByText('DEMO 20');expect(screen.queryByText('DEMO done')).toBeNull();expect(screen.queryByText('DEMO 23')).toBeNull();
 fireEvent.click(screen.getByRole('button',{name:/DEMO 20/}));expect(open).toHaveBeenCalledWith('20');
});
it('keeps an ineligible occurrence visible without presenting its dose as reviewed instructions',async()=>{
 vi.spyOn(api,'doseFollowUps').mockResolvedValue({items:[{...item,can_report:false,unavailable_reason:'review_required'}],has_more:false,timezone:'Asia/Singapore',as_of:new Date(now).toISOString()});
 render(<LateDoseFollowUps/>);await screen.findByText('DEMO medicine');
 expect(screen.getByText(/Saved plan needs review/)).toBeTruthy();expect(screen.queryByRole('button',{name:'Report dose status'})).toBeNull();expect(screen.queryByText(/Per dose/)).toBeNull();
});
it('shows all recent report rows at one disclosure level and only adds report actions when the API authorizes them',async()=>{
 const rows:DoseFollowUp[]=Array.from({length:5},(_,index)=>{const allowed=index===1||index===3;const unavailableReason:'review_required'|null=allowed?null:'review_required';return {...item,occurrence_id:`demo-occ-${index}`,can_report:allowed,unavailable_reason:unavailableReason};});
 vi.spyOn(api,'doseFollowUps').mockResolvedValue({items:rows,has_more:false,timezone:'Asia/Singapore',as_of:new Date(now).toISOString()});
 render(<LateDoseFollowUps/>);await screen.findAllByText('DEMO medicine');
 expect(screen.getAllByRole('button',{name:'Report dose status'})).toHaveLength(2);
 expect(screen.getAllByText('Review the saved medication and plan before reporting this occurrence.')).toHaveLength(3);
 expect(document.querySelector('.late-report-help details')).toBeNull();expect(screen.getByText(/Late reporting is available/)).toBeTruthy();
 expect(screen.queryByRole('button',{name:/View all .* reports/})).toBeNull();expect(screen.queryByRole('button',{name:'Show fewer'})).toBeNull();
});
it('Today shows only eligible unresolved doses on the API patient-local date',async()=>{
 vi.spyOn(api,'doseFollowUps').mockResolvedValue({items:[
  {...item,occurrence_id:'yesterday',due_at:'2026-10-18T15:00:00Z'},
  {...item,occurrence_id:'today',due_at:'2026-10-18T16:00:00Z'},
  {...item,occurrence_id:'not-eligible',due_at:'2026-10-18T17:00:00Z',can_report:false},
  {...item,occurrence_id:'reported',due_at:'2026-10-18T18:00:00Z',report_id:'demo-report'},
 ],has_more:false,timezone:'Asia/Singapore',as_of:'2026-10-19T04:00:00Z'});
 const history=vi.fn();render(<LateDoseFollowUps todayOnly onHistory={history}/>);
 expect(await screen.findByRole('button',{name:'Record status'})).toBeTruthy();expect(screen.getByText(/12:00.*Not recorded/)).toBeTruthy();
 expect(screen.queryByText(/yesterday|not-eligible|reported/)).toBeNull();expect(screen.getByText('Not recorded does not mean not taken.')).toBeTruthy();
 expect(screen.getByRole('heading',{name:"Today's confirmation"})).toBeTruthy();expect(screen.getByText('1 item')).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'View all medication records'}));expect(history).toHaveBeenCalledOnce();
});
it('keeps existing report correction access available in the Records workflow',async()=>{
 const read=vi.spyOn(api,'doseFollowUps').mockImplementation(async includeReported=>({items:includeReported?[{...item,can_report:true,report_id:'demo-report',intake_status:'unsure'}]:[],has_more:false,timezone:'Asia/Singapore',as_of:new Date(now).toISOString()}));
 vi.spyOn(api,'lateReportHistory').mockResolvedValue({original:null,corrections:[]});render(<LateDoseFollowUps/>);
 fireEvent.click(await screen.findByRole('checkbox',{name:'Include reported occurrences to review or correct'}));
 fireEvent.click(await screen.findByRole('button',{name:'Review or correct report'}));await act(async()=>{await Promise.resolve();});expect(screen.getByRole('dialog')).toBeTruthy();expect(read).toHaveBeenLastCalledWith(true);
});
it('Care Task statuses and dates use the configured timezone and invalid dates stay findable in List',()=>{
 expect(careTaskLocalDate('2026-10-18T16:30:00Z','Asia/Singapore')).toBe('2026-10-19');
 expect(taskView(task('edge','2026-10-18T15:59:59Z'),now)).toBe('overdue');
 expect(taskView(task('invalid','not-a-date'),now)).toBe('pending');
 const days=careTaskMonthDays('2026-10');expect(days).toHaveLength(34);expect(days[3]).toBe('2026-10-01');expect(shiftCareTaskMonth('2026-12',1)).toBe('2027-01');
 expect(sortCareTasks([task('done','2026-10-18T00:00:00Z','completed'),task('pending','2026-10-20T00:00:00Z'),task('late','2026-10-18T00:00:00Z')],now).map(row=>row.id)).toEqual(['late','pending','done']);
});
it.each(['reported_taken','reported_not_taken','unsure'] as const)('late %s stays a patient report and requires matching server confirmation',async status=>{
 vi.spyOn(api,'doseFollowUps').mockResolvedValue({items:[{...item,can_report:true}],has_more:false,timezone:'Asia/Singapore',as_of:new Date(now).toISOString()});
 vi.spyOn(api,'lateReportHistory').mockResolvedValue({original:null,corrections:[]});
 const prepare=vi.spyOn(api,'prepareLateReport').mockImplementation(async(_id,proposed)=>({challenge_id:'demo-challenge',session_id:'demo-session',expires_at:'2026-10-19T04:10:00Z',occurrence:item,proposed,timezone:'Asia/Singapore'}));
 const confirm=vi.spyOn(api,'confirmLateReport').mockImplementation(async(_id,challenge:LateReportChallenge)=>({...challenge.proposed,patient_id:'demo-owner',occurrence_id:item.occurrence_id,regimen_id:item.regimen_id,recorded_at:new Date(now).toISOString(),version:1,idempotency_key:'demo-key',ingestion_proven:false,visual_status:'not_checked'}));
 render(<LateDoseFollowUps/>);fireEvent.click(await screen.findByRole('button',{name:'Report dose status'}));
 const radios=screen.getAllByRole('radio');fireEvent.click(radios[status==='reported_taken'?0:status==='reported_not_taken'?1:2]!);
 fireEvent.click(screen.getByRole('button',{name:'Review report'}));expect(prepare).not.toHaveBeenCalled();expect(screen.getByRole('combobox')).toBe(document.activeElement);
 fireEvent.change(screen.getByRole('combobox'),{target:{value:'forgot_to_record'}});fireEvent.click(screen.getByRole('button',{name:'Review report'}));
 await screen.findByText('Review your report');expect(confirm).not.toHaveBeenCalled();expect(screen.getByText(/not proof of ingestion/)).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'Confirm report'}));await waitFor(()=>expect(confirm).toHaveBeenCalledOnce());
 expect(prepare).toHaveBeenCalledWith(item.occurrence_id,expect.objectContaining({intake_status:status,reason:'forgot_to_record',actual_administration_at:null}));
});

it('does not request unavailable late reports or pretend they are empty',()=>{
 const read=vi.spyOn(api,'doseFollowUps');render(<LateDoseFollowUps enabled={false}/>);
 expect(screen.getByRole('heading',{name:'Medication reports to confirm'})).toBeTruthy();
 expect(screen.getByRole('status').textContent).toContain('not enabled');expect(read).not.toHaveBeenCalled();
 expect(screen.queryByRole('button',{name:'Retry'})).toBeNull();
});
it('shows all bounded API occurrences without a second expansion or query',async()=>{
 const read=vi.spyOn(api,'doseFollowUps').mockResolvedValue({items:Array.from({length:5},(_,i)=>({...item,occurrence_id:`demo-${i}`,medication_name:`DEMO medicine ${i}`})),has_more:false,timezone:'Asia/Singapore',as_of:new Date(now).toISOString()});
 render(<LateDoseFollowUps/>);await screen.findByText('DEMO medicine 0');expect(screen.getByText('DEMO medicine 4')).toBeTruthy();
 expect(screen.queryByRole('button',{name:'View all 5 reports'})).toBeNull();expect(read).toHaveBeenCalledOnce();
});
it('requires checking an unusually old year before the historical review',()=>{
 render(<CareTaskForm regimens={[]} onCancel={vi.fn()} onSaved={vi.fn()}/>);
 fireEvent.change(screen.getByLabelText('Title (required)'),{target:{value:'DEMO old'}});
 fireEvent.change(screen.getByLabelText('Date (required)'),{target:{value:'2004-10-18'}});
 fireEvent.change(screen.getByLabelText('Time (required)'),{target:{value:'08:00'}});
 fireEvent.change(screen.getByLabelText('Advance reminder'),{target:{value:'none'}});
 fireEvent.click(screen.getByRole('button',{name:'Review and save'}));
 const confirm=screen.getByRole('button',{name:'Confirm historical entry'}) as HTMLButtonElement;expect(confirm.disabled).toBe(true);
 fireEvent.click(screen.getByRole('checkbox',{name:/2004-10-18/}));expect(confirm.disabled).toBe(false);
});

it('keeps legacy care-task entry available without offering unsupported advance reminders',()=>{
 render(<CareTaskForm extended={false} regimens={[]} onCancel={vi.fn()} onSaved={vi.fn()}/>);
 expect((screen.getByLabelText('Advance reminder') as HTMLSelectElement).disabled).toBe(true);
 expect((screen.getByLabelText('Advance reminder') as HTMLSelectElement).value).toBe('0');
 expect(screen.getByRole('status').textContent).toContain('not enabled');
});
