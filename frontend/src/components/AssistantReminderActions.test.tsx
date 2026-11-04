// @vitest-environment jsdom
import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor,within} from '@testing-library/react';
import {api,type CalendarExportOptions} from '../api/client';
import type {WorkflowView} from '../api/assistantWorkflows';
import * as push from '../webPush';
import {AssistantWorkflow} from './AssistantWorkflow';
import {CalendarExportAction} from './ReminderSettings';
vi.mock('../webPush',()=>({pushSupported:vi.fn().mockReturnValue(true),currentWebPush:vi.fn(),enableWebPush:vi.fn(),disableWebPush:vi.fn()}));
afterEach(()=>{cleanup();vi.restoreAllMocks();vi.clearAllMocks();vi.unstubAllGlobals();});
const base:WorkflowView={task_id:'DEMO-reminder-task',revision:1,capability_id:'reminder.list',state:'collecting',save_mode:'allowed',storage_state:'saved',prompt_key:'assistant.reminder.read',input_fields:{days:7,page:0},visible_fields:{timezone:'Asia/Singapore',reminders_enabled:true,lead_minutes:15,days:7,page:0,page_count:1,medications:[{occurrence_id:'DEMO-projected',medication_name:'DEMO future medicine',due_at:'2099-10-20T12:00:00Z',remind_at:'2099-10-20T11:45:00Z',projected_only:true}],care_tasks:[],snoozes:[]},missing_fields:[],actions:[{kind:'choice',action_id:'reminder.days',options:[{value:'1',label_key:'assistant.reminder.days1'},{value:'3',label_key:'assistant.reminder.days3'},{value:'7',label_key:'assistant.reminder.days7'}]}],explanations:[],result_ref:null};
const options:CalendarExportOptions={range:'90',include_medications:true,include_tasks:true};
const calendarView:WorkflowView={...base,capability_id:'reminder.calendar.export',state:'ready_for_review',prompt_key:'assistant.reminder.calendar',input_fields:{...options},visible_fields:{},actions:[{kind:'download',capability_id:'reminder.calendar.export',owned_ref:null}]};
const ics='BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nSUMMARY:DEMO\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n';
function urls(){vi.spyOn(URL,'createObjectURL').mockReturnValue('blob:DEMO-calendar');vi.spyOn(URL,'revokeObjectURL').mockImplementation(()=>{});vi.spyOn(HTMLAnchorElement.prototype,'click').mockImplementation(()=>{});}
const blob=()=>({text:async()=>ics}) as Blob;

it('shows projected reminders without calling the dose-materializing native plan endpoint',async()=>{
 const plan=vi.spyOn(api,'reminderPlan');render(<AssistantWorkflow view={base} busy={false} onEvent={vi.fn()}/>);
 expect(await screen.findByText('DEMO future medicine')).toBeTruthy();expect(screen.getByText('Projected reminders do not create dose records or prove that a dose was taken.')).toBeTruthy();expect(plan).not.toHaveBeenCalled();
});

it('uses offered typed reminder windows without a write',async()=>{
 const send=vi.fn().mockResolvedValue({...base,revision:2,input_fields:{days:1,page:0}});render(<AssistantWorkflow view={base} busy={false} onEvent={send}/>);
 fireEvent.click(await screen.findByRole('button',{name:'Next 1 day'}));await waitFor(()=>expect(send).toHaveBeenCalledWith(expect.objectContaining({kind:'provide_fields',values:{days:1,page:0}})));
});

it('reuses the native calendar form and binds its selected options only after explicit export',async()=>{
 urls();const read=vi.spyOn(api,'reminderCalendar').mockResolvedValue(blob()),send=vi.fn().mockResolvedValue({...calendarView,revision:2});
 render(<AssistantWorkflow view={calendarView} busy={false} onEvent={send}/>);fireEvent.click(await screen.findByRole('button',{name:'Export Calendar'}));const dialog=await screen.findByRole('dialog');expect(within(dialog).getByRole('radio',{name:'Next 90 days'})).toHaveProperty('checked',true);expect(read).not.toHaveBeenCalled();
 fireEvent.click(within(dialog).getByRole('button',{name:'Cancel'}));expect(read).not.toHaveBeenCalled();fireEvent.click(screen.getByRole('button',{name:'Export Calendar'}));fireEvent.click(within(screen.getByRole('dialog')).getByRole('button',{name:'Export .ics'}));
 await waitFor(()=>expect(read).toHaveBeenCalledWith(options,{task_id:base.task_id,expected_revision:2}));expect(send).toHaveBeenCalledWith(expect.objectContaining({kind:'provide_fields',values:{...options,start_date:null,end_date:null}}));expect(URL.createObjectURL).toHaveBeenCalled();
});

it('retains calendar selections after a failed export',async()=>{
 vi.spyOn(api,'reminderCalendar').mockRejectedValue(new Error('DEMO unavailable'));render(<AssistantWorkflow view={calendarView} busy={false} onEvent={vi.fn().mockResolvedValue({...calendarView,revision:2})}/>);fireEvent.click(await screen.findByRole('button',{name:'Export Calendar'}));fireEvent.click(within(screen.getByRole('dialog')).getByRole('button',{name:'Export .ics'}));
 expect(await screen.findByRole('alert')).toBeTruthy();expect(screen.getByRole('radio',{name:'Next 90 days'})).toHaveProperty('checked',true);
});

it('never starts a late calendar download after the native form unmounts',async()=>{
 urls();let resolve!:(value:Blob)=>void;vi.spyOn(api,'reminderCalendar').mockReturnValue(new Promise(done=>{resolve=done;}));
 const mounted=render(<CalendarExportAction/>);fireEvent.click(screen.getByRole('button',{name:'Export Calendar'}));fireEvent.click(within(screen.getByRole('dialog')).getByRole('button',{name:'Export .ics'}));mounted.unmount();resolve(blob());
 await new Promise(done=>setTimeout(done,0));expect(URL.createObjectURL).not.toHaveBeenCalled();
});

it('reads device status only on click without exposing subscription details or permission/sender actions',async()=>{
 const permission=vi.fn();vi.stubGlobal('Notification',{permission:'granted',requestPermission:permission});vi.mocked(push.currentWebPush).mockResolvedValue({browserSubscribed:true,id:'DEMO-private-subscription',enabled:true});
 const config=vi.spyOn(api,'pushConfig').mockResolvedValue({available:true,public_key:'DEMO-public-key',test_available:true}),test=vi.spyOn(api,'testPush'),send=vi.fn();
 render(<AssistantWorkflow view={{...base,capability_id:'notification.status',prompt_key:'assistant.reminder.device',input_fields:{},visible_fields:{},actions:[]}} busy={false} onEvent={send}/>);
 const check=await screen.findByRole('button',{name:'Check device notification status'});expect(config).not.toHaveBeenCalled();fireEvent.click(check);expect(await screen.findByText('This device is subscribed; delivery has not been verified.')).toBeTruthy();
 expect(screen.queryByText('DEMO-private-subscription')).toBeNull();expect(screen.queryByText('DEMO-public-key')).toBeNull();expect(permission).not.toHaveBeenCalled();expect(push.enableWebPush).not.toHaveBeenCalled();expect(push.disableWebPush).not.toHaveBeenCalled();expect(test).not.toHaveBeenCalled();expect(send).not.toHaveBeenCalled();
});
