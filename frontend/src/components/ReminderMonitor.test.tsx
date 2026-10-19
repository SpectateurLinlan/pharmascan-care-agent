// @vitest-environment jsdom
import {afterEach,expect,it,vi} from 'vitest';
import {act,cleanup,render,screen} from '@testing-library/react';
import {api} from '../api/client';
import {ReminderMonitor} from './ReminderMonitor';
vi.mock('../api/client',()=>({api:{reminderAlerts:vi.fn()}}));
vi.mock('../language',()=>({useLanguage:()=>({language:'en',t:(s:string)=>s,preferences:{timezone:'Asia/Singapore'}})}));
afterEach(()=>{cleanup();vi.useRealTimers();vi.resetAllMocks();sessionStorage.clear();});
const port={kind:'noop' as const,support:()=> 'unsupported' as const,notify:vi.fn(),requestPermission:vi.fn()};
it('keeps one request in flight and backs off persistent failures before recovering',async()=>{
 vi.useFakeTimers();vi.setSystemTime(new Date('2026-10-19T00:00:00Z'));
 vi.mocked(api.reminderAlerts).mockRejectedValue(new Error('DEMO unavailable'));
 await act(async()=>{render(<ReminderMonitor enabled onReview={vi.fn()} port={port}/>);});
 expect(api.reminderAlerts).toHaveBeenCalledTimes(1);
 expect(screen.getByRole('status').textContent).toContain('Could not refresh');
 await act(async()=>{await vi.advanceTimersByTimeAsync(15000);});
 expect(api.reminderAlerts).toHaveBeenCalledTimes(2);
 await act(async()=>{await vi.advanceTimersByTimeAsync(15000);});
 expect(api.reminderAlerts).toHaveBeenCalledTimes(2);
 vi.mocked(api.reminderAlerts).mockResolvedValue([]);
 await act(async()=>{await vi.advanceTimersByTimeAsync(15000);});
 expect(api.reminderAlerts).toHaveBeenCalledTimes(3);
 expect(screen.queryByRole('status')).toBeNull();
 await act(async()=>{await vi.advanceTimersByTimeAsync(15000);});
 expect(api.reminderAlerts).toHaveBeenCalledTimes(4);
});
it('does not overlap a slow request or update after unmount',async()=>{
 vi.useFakeTimers();let resolve!:(rows:[])=>void;
 vi.mocked(api.reminderAlerts).mockReturnValue(new Promise(r=>{resolve=r;}));
 const {unmount}=render(<ReminderMonitor enabled onReview={vi.fn()} port={port}/>);
 await act(async()=>{await vi.advanceTimersByTimeAsync(60000);});
 expect(api.reminderAlerts).toHaveBeenCalledTimes(1);
 unmount();await act(async()=>{resolve([]);});
 await act(async()=>{await vi.advanceTimersByTimeAsync(30000);});
 expect(api.reminderAlerts).toHaveBeenCalledTimes(1);
});
