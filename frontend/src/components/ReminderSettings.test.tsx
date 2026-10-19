// @vitest-environment jsdom
import {afterEach,expect,it,vi} from 'vitest';
import * as React from 'react';
import {act,cleanup,fireEvent,render,screen,waitFor,within} from '@testing-library/react';
import {CalendarExportAction,ReminderSettings} from './ReminderSettings';
import {ApiError,api,type PatientPreferences} from '../api/client';
import {LanguageProvider,useLanguage} from '../language';
import {AutoDismissNotice} from './primitives';
import type {CareTask} from '../api/care';

vi.mock('../api/client',()=>({ApiError:class extends Error{code:string;status:number;constructor(status:number,body:{code:string;message:string}){super(body.message);this.code=body.code;this.status=status;}},api:{careTasks:vi.fn().mockResolvedValue([]),reminderPlan:vi.fn(),reminderCalendar:vi.fn(),preferences:vi.fn(),updatePreferences:vi.fn(),pushSubscriptions:vi.fn().mockResolvedValue([]),pushConfig:vi.fn().mockResolvedValue({available:false,public_key:null,test_available:false}),testPush:vi.fn(),revokePushSubscription:vi.fn()}}));
afterEach(()=>{cleanup();vi.clearAllMocks();});

const savedPreferences=(overrides:Partial<PatientPreferences>={}):PatientPreferences=>({patient_id:'DEMO-owner',preferred_language:'en',speech_locale:'en-SG',text_size:'standard',voice_enabled:false,tts_autoplay:false,reminder_lead_minutes:30,reminders_enabled:true,timezone:'Asia/Singapore',created_at:'2026-10-19T00:00:00Z',updated_at:'2026-10-19T00:00:00Z',...overrides});
const reminders=()=>Array.from({length:5},(_,index)=>({occurrence_id:`DEMO-${index}`,regimen_id:'DEMO-regimen',rule_id:'DEMO-rule',medication_name:`DEMO medicine ${index}`,due_at:'2099-10-17T08:00:00Z',remind_at:'2099-10-17T08:00:00Z',slot:'08:00'}));
function careTask(overrides:Partial<CareTask>={}):CareTask{return{id:'DEMO-followup',title:'DEMO follow-up',category:'medication_review',due_at:'2099-10-20T08:00:00Z',medication_id:null,regimen_id:null,notes:'',reminder_minutes:60,reminder_offsets:[15,30],status:'open',patient_id:'DEMO-owner',source:'patient_reported',version:1,history:[],created_at:'2026-10-19T00:00:00Z',updated_at:'2026-10-19T00:00:00Z',demo_only:true,...overrides};}

it('loads actual upcoming reminders collapsed, then shows all reminders when expanded',async()=>{
 vi.mocked(api.reminderPlan).mockResolvedValue(reminders());
 render(<ReminderSettings/>);
 const disclosure=await screen.findByRole('button',{name:/Upcoming Medication Reminders · 5 reminders/});
 expect(disclosure.getAttribute('aria-expanded')).toBe('false');expect(screen.queryByText('DEMO medicine 0')).toBeNull();
 fireEvent.click(disclosure);const list=document.getElementById('upcoming-reminder-list')!;
 expect(within(list).getAllByRole('listitem')).toHaveLength(5);
 expect(screen.queryByRole('button',{name:'View All Reminders'})).toBeNull();
 fireEvent.click(disclosure);expect(screen.queryByText('DEMO medicine 0')).toBeNull();
});

it('keeps failed reminder reads distinct from a real empty schedule',async()=>{
 vi.mocked(api.reminderPlan).mockRejectedValue(new Error('DEMO reminder service unavailable'));
 render(<ReminderSettings/>);await screen.findByText('Could not load reminders. Your medication records have not changed.');
 expect(screen.queryByText('No upcoming medication reminders.')).toBeNull();expect(screen.getByRole('alert')).toBeTruthy();
});

it('opens the matching Care Task without requiring Web Push',async()=>{
 vi.mocked(api.reminderPlan).mockResolvedValue([]);vi.mocked(api.careTasks).mockResolvedValue([careTask()]);const onOpenCareTask=vi.fn();
 render(<ReminderSettings onOpenCareTask={onOpenCareTask}/>);
 fireEvent.click(await screen.findByRole('button',{name:'View task: DEMO follow-up'}));
 expect(onOpenCareTask).toHaveBeenCalledWith('DEMO-followup');expect(screen.getByRole('switch',{name:'Receive Device Notifications'}).hasAttribute('disabled')).toBe(true);expect(screen.getAllByText('This application is not configured for new device subscriptions.')).toHaveLength(2);
});

it('keeps independent Care Task rows and does not duplicate a task for its reminder offsets',async()=>{
 vi.mocked(api.reminderPlan).mockResolvedValue([]);vi.mocked(api.careTasks).mockResolvedValue([careTask(),careTask({id:'DEMO-followup-2',title:'DEMO second follow-up'})]);
 render(<ReminderSettings multipleCareRemindersEnabled onOpenCareTask={vi.fn()}/>);
 expect(await screen.findByText(/2 upcoming Care Tasks/)).toBeTruthy();fireEvent.click(screen.getByRole('button',{name:'View ›'}));
 const list=screen.getByRole('list',{name:''});expect(within(list).getAllByRole('listitem')).toHaveLength(2);
});

it('persists medication reminder switch state, blocks duplicate changes and shows a transient success toast',async()=>{
 vi.mocked(api.reminderPlan).mockResolvedValue([]);let resolveSave!:(value:PatientPreferences)=>void;
 vi.mocked(api.updatePreferences).mockImplementation(()=>new Promise(resolve=>{resolveSave=resolve;}));
 render(<LanguageProvider><ReminderSettings/></LanguageProvider>);
 const toggle=await screen.findByRole('switch',{name:'Medication Reminders'});expect(toggle.getAttribute('aria-checked')).toBe('true');
 fireEvent.click(toggle);expect(toggle.hasAttribute('disabled')).toBe(true);expect(toggle.getAttribute('aria-checked')).toBe('true');
 expect(await screen.findByRole('status')).toBeTruthy();fireEvent.click(toggle);expect(api.updatePreferences).toHaveBeenCalledTimes(1);
 await act(async()=>resolveSave(savedPreferences({reminders_enabled:false})));await waitFor(()=>expect(toggle.getAttribute('aria-checked')).toBe('false'));
 expect(await screen.findByText('Medication reminder preference saved.')).toBeTruthy();expect(screen.queryByLabelText('Medication Reminder Timing')).toBeNull();
});

it('auto-dismisses success toasts after approximately four seconds',()=>{
 vi.useFakeTimers();render(<AutoDismissNotice>Saved</AutoDismissNotice>);expect(screen.getByRole('status').textContent).toContain('Saved');
 act(()=>vi.advanceTimersByTime(4500));expect(screen.queryByRole('status')).toBeNull();vi.useRealTimers();
});

it('retains the confirmed medication reminder state after a failed save',async()=>{
 vi.mocked(api.reminderPlan).mockResolvedValue([]);vi.mocked(api.updatePreferences).mockRejectedValue(new Error('DEMO save failed'));
 render(<LanguageProvider><ReminderSettings/></LanguageProvider>);
 const toggle=await screen.findByRole('switch',{name:'Medication Reminders'});fireEvent.click(toggle);
 await screen.findByRole('alert');expect(toggle.getAttribute('aria-checked')).toBe('true');
 expect(screen.getByLabelText('Reminder Lead Time')).toBeTruthy();
});

it('saves the reminder lead-time preference using the existing preferences API',async()=>{
 vi.mocked(api.reminderPlan).mockResolvedValue([]);vi.mocked(api.preferences).mockRejectedValue(new Error('DEMO not loaded in this isolated test'));
 vi.mocked(api.updatePreferences).mockResolvedValue(savedPreferences({reminder_lead_minutes:15}));
 render(<LanguageProvider><ReminderSettings/></LanguageProvider>);
 const timing=await screen.findByLabelText('Reminder Lead Time') as HTMLSelectElement;
 expect([...timing.options].map(option=>option.textContent)).toEqual(['At scheduled time','15 minutes before','30 minutes before','1 hour before']);
 fireEvent.change(timing,{target:{value:'15'}});await waitFor(()=>expect(api.updatePreferences).toHaveBeenCalledWith({reminder_lead_minutes:15}));
});

it('keeps the compact page labels in Chinese and exposes a keyboard-operable switch',async()=>{
 vi.mocked(api.reminderPlan).mockResolvedValue([]);vi.mocked(api.updatePreferences).mockResolvedValue(savedPreferences({preferred_language:'zh'}));
 function ChooseChinese(){const {setLanguage}=useLanguage();React.useEffect(()=>setLanguage('zh'),[setLanguage]);return null;}
 render(<LanguageProvider><ChooseChinese/><ReminderSettings/></LanguageProvider>);
 const toggle=await screen.findByRole('switch',{name:/\u5b9a\u65f6\u7528\u836f\u63d0\u9192/});
 expect(screen.getByRole('heading',{name:'\u63d0\u9192\u8ba1\u5212'})).toBeTruthy();expect(screen.getByRole('heading',{name:'\u7528\u836f\u8ddf\u8fdb\u63d0\u9192'})).toBeTruthy();
 expect(screen.getByRole('heading',{name:'\u6b64\u8bbe\u5907\u901a\u77e5'})).toBeTruthy();expect(screen.getByRole('button',{name:/\u901a\u77e5\u8bbe\u7f6e/})).toBeTruthy();
 expect(screen.getByRole('button',{name:/\u6d4b\u8bd5\u901a\u77e5/}).hasAttribute('disabled')).toBe(true);
 expect(screen.queryByText(/\u5c1a\u672a\u9a8c\u8bc1|Not yet verified/)).toBeNull();
 toggle.focus();expect(document.activeElement).toBe(toggle);expect(toggle.getAttribute('aria-checked')).toBe('true');
});

it('exports the existing calendar independently of background push',async()=>{
 vi.mocked(api.reminderCalendar).mockResolvedValue(new Blob(['BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:DEMO\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n'],{type:'text/calendar'}));
 vi.spyOn(URL,'createObjectURL').mockReturnValue('blob:DEMO');vi.spyOn(URL,'revokeObjectURL').mockImplementation(()=>undefined);const download=vi.spyOn(HTMLAnchorElement.prototype,'click').mockImplementation(()=>undefined);
 render(<CalendarExportAction/>);fireEvent.click(screen.getByRole('button',{name:'Export Calendar'}));
 const dialog=await screen.findByRole('dialog',{name:'Export to Calendar'});
 expect((within(dialog).getByRole('radio',{name:'Next 30 days'}) as HTMLInputElement).checked).toBe(true);
 expect(within(dialog).getByText('One-time calendar import. Changes in MediThread will not update this file.')).toBeTruthy();
 fireEvent.click(within(dialog).getByRole('button',{name:'Export .ics'}));
 await screen.findByText('Calendar file generated. Import it into your calendar app.');expect(api.reminderCalendar).toHaveBeenCalledWith({range:'30',include_medications:true,include_tasks:true});expect(download).toHaveBeenCalledOnce();
 expect(screen.queryByRole('dialog')).toBeNull();
 expect(screen.getByText('Exported events will not sync automatically.')).toBeTruthy();
});

it('validates a custom range and passes the selected date and content options to the API',async()=>{
 vi.mocked(api.reminderCalendar).mockResolvedValue(new Blob(['BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n'],{type:'text/calendar'}));
 vi.spyOn(URL,'createObjectURL').mockReturnValue('blob:DEMO');vi.spyOn(URL,'revokeObjectURL').mockImplementation(()=>undefined);vi.spyOn(HTMLAnchorElement.prototype,'click').mockImplementation(()=>undefined);
 render(<CalendarExportAction/>);fireEvent.click(screen.getByRole('button',{name:'Export Calendar'}));const dialog=await screen.findByRole('dialog');
 fireEvent.click(within(dialog).getByRole('radio',{name:'Custom date range'}));
 fireEvent.change(within(dialog).getByLabelText('Start date'),{target:{value:'2099-12-20'}});fireEvent.change(within(dialog).getByLabelText('End date'),{target:{value:'2099-12-21'}});
 fireEvent.click(within(dialog).getByRole('checkbox',{name:'Care Task reminders'}));
 fireEvent.click(within(dialog).getByRole('button',{name:'Export .ics'}));
 await waitFor(()=>expect(api.reminderCalendar).toHaveBeenCalledWith({range:'custom',start_date:'2099-12-20',end_date:'2099-12-21',include_medications:true,include_tasks:false}));
});

it('keeps the dialog open with a specific message when a custom range is reversed',async()=>{
 render(<CalendarExportAction/>);fireEvent.click(screen.getByRole('button',{name:'Export Calendar'}));const dialog=await screen.findByRole('dialog');
 fireEvent.click(within(dialog).getByRole('radio',{name:'Custom date range'}));
 fireEvent.change(within(dialog).getByLabelText('Start date'),{target:{value:'2099-12-20'}});fireEvent.change(within(dialog).getByLabelText('End date'),{target:{value:'2099-12-19'}});
 fireEvent.submit(within(dialog).getByRole('button',{name:'Export .ics'}).closest('form')!);
 expect(await within(dialog).findByText('The end date must be on or after the start date.')).toBeTruthy();expect(api.reminderCalendar).not.toHaveBeenCalled();
});

it('shows the server event-limit explanation and keeps the dialog open',async()=>{
 vi.mocked(api.reminderCalendar).mockRejectedValue(new ApiError(422,{code:'INVALID_INPUT',message:'Calendar export exceeds 500 events. Choose a shorter date range or remove an export category.',rule_id:null}));
 render(<CalendarExportAction/>);fireEvent.click(screen.getByRole('button',{name:'Export Calendar'}));const dialog=await screen.findByRole('dialog');
 fireEvent.click(within(dialog).getByRole('button',{name:'Export .ics'}));
 expect(await within(dialog).findByText(/Calendar export exceeds 500 events/)).toBeTruthy();expect(screen.getByRole('dialog')).toBeTruthy();
});

it('keeps the dialog open and starts no download for an invalid ICS response',async()=>{
 vi.mocked(api.reminderCalendar).mockResolvedValue(new Blob(['not an ICS file'],{type:'text/calendar'}));const download=vi.spyOn(HTMLAnchorElement.prototype,'click').mockImplementation(()=>undefined);
 render(<CalendarExportAction/>);fireEvent.click(screen.getByRole('button',{name:'Export Calendar'}));const dialog=await screen.findByRole('dialog');
 fireEvent.click(within(dialog).getByRole('button',{name:'Export .ics'}));
 expect(await within(dialog).findByRole('alert')).toBeTruthy();expect(within(dialog).getByRole('button',{name:'Cancel'})).toBeTruthy();expect(download).not.toHaveBeenCalled();
});

it('shows the export pending state and blocks duplicate submissions',async()=>{
 let resolveExport!:(value:Blob)=>void;
 vi.spyOn(URL,'createObjectURL').mockReturnValue('blob:DEMO');vi.spyOn(URL,'revokeObjectURL').mockImplementation(()=>undefined);vi.spyOn(HTMLAnchorElement.prototype,'click').mockImplementation(()=>undefined);
 vi.mocked(api.reminderCalendar).mockImplementation(()=>new Promise(resolve=>{resolveExport=resolve;}));
 render(<CalendarExportAction/>);fireEvent.click(screen.getByRole('button',{name:'Export Calendar'}));const dialog=await screen.findByRole('dialog');
 fireEvent.click(within(dialog).getByRole('button',{name:'Export .ics'}));
 const exporting=await within(dialog).findByRole('button',{name:'Exporting calendar…'});expect(exporting.hasAttribute('disabled')).toBe(true);
 fireEvent.click(exporting);expect(api.reminderCalendar).toHaveBeenCalledTimes(1);
 await act(async()=>resolveExport(new Blob(['BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n'],{type:'text/calendar'})));
});

it('prevents an empty content selection and closes the export dialog with Escape',async()=>{
 render(<CalendarExportAction/>);fireEvent.click(screen.getByRole('button',{name:'Export Calendar'}));const dialog=await screen.findByRole('dialog');
 fireEvent.click(within(dialog).getByRole('checkbox',{name:'Medication reminders'}));fireEvent.click(within(dialog).getByRole('checkbox',{name:'Care Task reminders'}));
 fireEvent.click(within(dialog).getByRole('button',{name:'Export .ics'}));expect(await within(dialog).findByRole('alert')).toBeTruthy();expect(api.reminderCalendar).not.toHaveBeenCalled();
 fireEvent.keyDown(dialog,{key:'Escape'});await waitFor(()=>expect(screen.queryByRole('dialog')).toBeNull());
});

it('localizes the export action and dialog controls in Chinese',async()=>{
 function ChooseChinese(){const {setLanguage}=useLanguage();React.useEffect(()=>setLanguage('zh'),[setLanguage]);return null;}
 render(<LanguageProvider><ChooseChinese/><CalendarExportAction/></LanguageProvider>);
 fireEvent.click(await screen.findByRole('button',{name:'导出日历'}));const dialog=await screen.findByRole('dialog',{name:'导出到日历'});
 expect(within(dialog).getByRole('radio',{name:'未来 30 天'})).toBeTruthy();expect(within(dialog).getByRole('radio',{name:'完整剩余疗程'})).toBeTruthy();
 expect(within(dialog).getByRole('checkbox',{name:'定时用药提醒'})).toBeTruthy();expect(within(dialog).getByRole('button',{name:'导出 .ics'})).toBeTruthy();
 fireEvent.click(within(dialog).getByRole('button',{name:'取消'}));await waitFor(()=>expect(screen.queryByRole('dialog')).toBeNull());
});
