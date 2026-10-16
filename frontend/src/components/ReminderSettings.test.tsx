// @vitest-environment jsdom
import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,render,screen} from '@testing-library/react';
import {ReminderSettings} from './ReminderSettings';
import {api} from '../api/client';
vi.mock('../api/client',()=>({ApiError:class extends Error{},api:{reminderPlan:vi.fn(),pushSubscriptions:vi.fn().mockResolvedValue([]),pushConfig:vi.fn().mockResolvedValue({available:false,public_key:null})}}));
afterEach(()=>{cleanup();vi.clearAllMocks();});
it('failed reminder reads remain unavailable instead of an empty schedule',async()=>{
 vi.mocked(api.reminderPlan).mockRejectedValue(new Error('DEMO reminder service unavailable'));
 render(<ReminderSettings/>);await screen.findByText('Could not load reminders. Your medication records have not changed.');
 expect(screen.queryByText(/No upcoming timed reminders/)).toBeNull();expect(screen.getByRole('alert')).toBeTruthy();
});
