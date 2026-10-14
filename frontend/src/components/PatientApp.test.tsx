// @vitest-environment jsdom
import {afterEach,expect,it,vi} from 'vitest';
import {act,cleanup,fireEvent,render,screen} from '@testing-library/react';
import {ReminderMonitor} from './ReminderMonitor';
import {MeScreen} from './MeScreen';
import {EnrollScreen,courseEndForDuration} from './EnrollScreen';
import {api} from '../api/client';
import type {AccountPort} from '../api/auth';
vi.mock('../api/client',()=>({ApiError:class extends Error{},api:{reminderAlerts:vi.fn(),snoozeReminder:vi.fn(),createDraft:vi.fn()}}));
afterEach(()=>{cleanup();sessionStorage.clear();vi.useRealTimers();vi.resetAllMocks();});
it('automatically prompts after server due status, even without notification permission, and deduplicates',async()=>{
 vi.useFakeTimers();const notify=vi.fn();const row={key:'DEMO-occurrence:time',occurrence_id:'DEMO-occurrence',regimen_id:'DEMO-regimen',medication_name:'DEMO Metformin',dose_amount:500,dose_unit:'mg',food_instruction:'after food',due_at:'2026-10-14T12:00:00Z',remind_at:'2026-10-14T12:00:00Z'};
 vi.mocked(api.reminderAlerts).mockResolvedValueOnce([]).mockResolvedValue([row]);
 await act(async()=>{render(<ReminderMonitor enabled onReview={vi.fn()} port={{kind:'noop',support:()=> 'denied',requestPermission:async()=> 'denied',notify}}/>);});
 expect(screen.queryByRole('dialog')).toBeNull();await act(async()=>{await vi.advanceTimersByTimeAsync(15000);});
 expect(screen.getByRole('dialog',{name:'Medication reminder'}).textContent).toContain('500 mg');expect(notify).not.toHaveBeenCalled();
 fireEvent.click(screen.getByRole('button',{name:'Dismiss'}));await act(async()=>{await vi.advanceTimersByTimeAsync(15000);});expect(screen.queryByRole('dialog')).toBeNull();
});
it('shows a guest login, requires explicit account switching, and keeps Singpass outside primary account actions',async()=>{
 const auth:AccountPort={available:true,account:async()=>({kind:'guest',email:null,verified:false}),requestEmail:vi.fn().mockResolvedValue(undefined),verifyEmail:vi.fn().mockResolvedValue(undefined),passwordLogin:vi.fn().mockResolvedValue(undefined),setPassword:vi.fn().mockResolvedValue(undefined),signOut:vi.fn().mockResolvedValue(undefined)};
 render(<MeScreen auth={auth} onSettings={vi.fn()} onFeedback={vi.fn()} onIdentityChanged={vi.fn()}/>);await screen.findByText('Guest demo');
 expect(screen.queryByRole('button',{name:/Singpass/})).toBeNull();
 fireEvent.click(screen.getByRole('button',{name:'Sign in to an account'}));fireEvent.change(screen.getByLabelText('Email'),{target:{value:'synthetic@example.test'}});
 expect((screen.getByRole('button',{name:'Email code / Magic Link'}) as HTMLButtonElement).disabled).toBe(true);
 fireEvent.click(screen.getByRole('checkbox'));fireEvent.click(screen.getByRole('button',{name:'Email code / Magic Link'}));
 await screen.findByText('Check your email for a code or sign-in link.');expect(auth.requestEmail).toHaveBeenCalledWith('synthetic@example.test','login');
});
it('uses inclusive calendar duration and submits reviewed food instructions, not a guessed dose',async()=>{
 expect(courseEndForDuration('2026-10-14',7)).toBe('2026-10-20');expect(courseEndForDuration('',7)).toBeNull();expect(courseEndForDuration('2026-02-30',7)).toBeNull();
 vi.mocked(api.createDraft).mockResolvedValue({medication_id:'DEMO-m',regimen_id:'DEMO-r',state:'draft',source_id:'DEMO-s',missing_instructions:[],reviewable_field_ids:[],note:'demo_only'});
 render(<EnrollScreen sessionId={null} medications={null} onChanged={vi.fn()}/>);
 fireEvent.change(screen.getByLabelText('Medication name'),{target:{value:'DEMO Metformin'}});fireEvent.change(screen.getByLabelText('Dose amount'),{target:{value:'500'}});
 fireEvent.change(screen.getByLabelText('Course start date'),{target:{value:'2026-10-14'}});fireEvent.change(screen.getByLabelText('Number of days'),{target:{value:'7'}});fireEvent.change(screen.getByLabelText('Food instructions'),{target:{value:'after food'}});
 fireEvent.click(screen.getByRole('button',{name:'Create draft'}));await screen.findByText('Draft saved — not active yet.');
 expect(api.createDraft).toHaveBeenCalledWith(expect.objectContaining({dose_amount:500,course_end_date:'2026-10-20',food_instruction:'after food'}));
});
