// @vitest-environment jsdom
import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,render,screen} from '@testing-library/react';
import {SettingsScreen} from './SettingsScreen';
vi.mock('../api/client',()=>({api:{speechCapabilities:vi.fn().mockResolvedValue({cloud_tts_allowed:false})}}));
vi.mock('./ReminderSettings',()=>({ReminderSettings:()=> <div data-testid="reminder-editor"/>}));
afterEach(cleanup);
it('keeps language, text size and reminder controls on their own settings routes',()=>{
 const view=render(<SettingsScreen/>);
 expect(screen.queryByTestId('reminder-editor')).toBeNull();
 expect(screen.getByRole('slider',{name:/Text size/})).toBeTruthy();
 view.rerender(<SettingsScreen section="language"/>);
 expect(screen.getByLabelText('Settings language')).toBeTruthy();
 expect(screen.queryByRole('slider',{name:/Text size/})).toBeNull();
 view.rerender(<SettingsScreen section="accessibility"/>);
 expect(screen.getByRole('slider',{name:/Text size/})).toBeTruthy();
 expect(screen.queryByLabelText('Settings language')).toBeNull();
 expect(screen.queryByTestId('reminder-editor')).toBeNull();
 view.rerender(<SettingsScreen section="reminders"/>);
 expect(screen.getByTestId('reminder-editor')).toBeTruthy();
 expect(screen.queryByRole('slider')).toBeNull();
});
