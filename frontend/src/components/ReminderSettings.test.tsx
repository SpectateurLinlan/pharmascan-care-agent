// @vitest-environment jsdom
import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,within} from '@testing-library/react';
import {ReminderSettings} from './ReminderSettings';
import {api} from '../api/client';
vi.mock('../api/client',()=>({ApiError:class extends Error{},api:{careTasks:vi.fn().mockResolvedValue([]),reminderPlan:vi.fn(),pushSubscriptions:vi.fn().mockResolvedValue([]),pushConfig:vi.fn().mockResolvedValue({available:false,public_key:null})}}));
afterEach(()=>{cleanup();vi.clearAllMocks();});
it('failed reminder reads remain unavailable instead of an empty schedule',async()=>{
 vi.mocked(api.reminderPlan).mockRejectedValue(new Error('DEMO reminder service unavailable'));
 render(<ReminderSettings/>);await screen.findByText('Could not load reminders. Your medication records have not changed.');
 expect(screen.queryByText(/No upcoming timed reminders/)).toBeNull();expect(screen.getByRole('alert')).toBeTruthy();
});
it('previews three real future plans and expands only the returned schedule',async()=>{
 vi.mocked(api.reminderPlan).mockResolvedValue(Array.from({length:5},(_,index)=>({occurrence_id:`DEMO-${index}`,regimen_id:'DEMO-regimen',rule_id:'DEMO-rule',medication_name:`DEMO medicine ${index}`,due_at:'2099-10-17T08:00:00Z',remind_at:'2099-10-17T08:00:00Z',slot:'08:00'})));
 render(<ReminderSettings/>);
 await screen.findByText(/DEMO medicine 0/);
 const list=document.getElementById('upcoming-reminder-list')!;
 expect(within(list).getAllByRole('listitem')).toHaveLength(3);
 fireEvent.click(screen.getByRole('button',{name:'View all upcoming reminders'}));
 expect(within(list).getAllByRole('listitem')).toHaveLength(5);
 fireEvent.click(screen.getByRole('button',{name:'Show fewer reminders'}));
 expect(within(list).getAllByRole('listitem')).toHaveLength(3);
});
