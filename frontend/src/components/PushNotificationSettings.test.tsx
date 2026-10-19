// @vitest-environment jsdom
// LOCAL/MOCK: no external push endpoint is contacted.
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {useEffect,useRef} from 'react';
import {act,cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {api} from '../api/client';
import {currentWebPush,disableWebPush,enableWebPush} from '../webPush';
import {PushNotificationSettings,NotificationGuide} from './PushNotificationSettings';
import {NotificationInvitation} from './NotificationInvitation';
import {LanguageProvider,useLanguage} from '../language';

vi.mock('../api/client',()=>({ApiError:class extends Error{},api:{pushConfig:vi.fn(),pushSubscriptions:vi.fn(),testPush:vi.fn(),revokePushSubscription:vi.fn(),updatePreferences:vi.fn()}}));
vi.mock('../webPush',()=>({pushSupported:()=>true,currentWebPush:vi.fn(),disableWebPush:vi.fn(),enableWebPush:vi.fn()}));
beforeEach(()=>{
 vi.stubGlobal('Notification',{permission:'granted',requestPermission:vi.fn()});
 vi.mocked(api.pushConfig).mockResolvedValue({available:true,public_key:'DEMO',test_available:true});
 vi.mocked(api.pushSubscriptions).mockResolvedValue([{id:'DEMO-current',enabled:true},{id:'DEMO-other',enabled:true}]);
 vi.mocked(currentWebPush).mockResolvedValue({browserSubscribed:true,id:'DEMO-current',enabled:true});
 vi.mocked(api.testPush).mockResolvedValue({status:'sent'});
 vi.mocked(api.revokePushSubscription).mockResolvedValue();
 vi.mocked(api.updatePreferences).mockResolvedValue({patient_id:'DEMO-owner',preferred_language:'zh',speech_locale:'en-SG',text_size:'standard',text_scale_percent:100,voice_enabled:false,tts_autoplay:false,reminders_enabled:true,reminder_lead_minutes:0,timezone:'Asia/Singapore',created_at:'2026-10-19T00:00:00Z',updated_at:'2026-10-19T00:00:00Z'});
 vi.mocked(disableWebPush).mockResolvedValue();vi.mocked(enableWebPush).mockResolvedValue();
});
afterEach(()=>{cleanup();localStorage.clear();vi.resetAllMocks();vi.unstubAllGlobals();});

it('shows only the confirmed current-device subscription and opens settings without prompting',async()=>{
 render(<PushNotificationSettings/>);const toggle=await screen.findByRole('switch',{name:'Receive Device Notifications'});
 expect(toggle.getAttribute('aria-checked')).toBe('true');expect(screen.getByText('This device is subscribed to notifications.')).toBeTruthy();
 expect(Notification.requestPermission).not.toHaveBeenCalled();fireEvent.click(screen.getByRole('button',{name:/Notification Settings/}));
 expect(await screen.findByRole('dialog')).toBeTruthy();expect(screen.getByText('Configured for device setup')).toBeTruthy();
 fireEvent.keyDown(screen.getByRole('dialog'),{key:'Escape'});await waitFor(()=>expect(screen.queryByRole('dialog')).toBeNull());
});

it('does not show the device switch enabled until subscribe succeeds and confirms',async()=>{
 vi.mocked(currentWebPush).mockResolvedValueOnce({browserSubscribed:false,id:null,enabled:false}).mockResolvedValueOnce({browserSubscribed:true,id:'DEMO-current',enabled:true});
 let resolveEnable!:()=>void;vi.mocked(enableWebPush).mockImplementation(()=>new Promise<void>(resolve=>{resolveEnable=resolve;}));
 render(<PushNotificationSettings/>);const toggle=await screen.findByRole('switch',{name:'Receive Device Notifications'});
 expect(toggle.getAttribute('aria-checked')).toBe('false');expect(Notification.requestPermission).not.toHaveBeenCalled();
 fireEvent.click(toggle);expect(toggle.hasAttribute('disabled')).toBe(true);expect(toggle.getAttribute('aria-checked')).toBe('false');
 await screen.findByText('Saving device notification setting…');fireEvent.click(toggle);expect(enableWebPush).toHaveBeenCalledTimes(1);
 await act(async()=>resolveEnable());await waitFor(()=>expect(toggle.getAttribute('aria-checked')).toBe('true'));
 expect(await screen.findByText('Device subscription saved.')).toBeTruthy();
});

it('retains the confirmed off state and explains a failed subscription change',async()=>{
 vi.mocked(currentWebPush).mockResolvedValueOnce({browserSubscribed:false,id:null,enabled:false});vi.mocked(enableWebPush).mockRejectedValue(new Error('DEMO permission denied'));
 render(<PushNotificationSettings/>);const toggle=await screen.findByRole('switch',{name:'Receive Device Notifications'});
 fireEvent.click(toggle);await screen.findByRole('alert');expect(toggle.getAttribute('aria-checked')).toBe('false');
 expect(screen.getByText('Device notifications are off.')).toBeTruthy();
});

it('disables this device only and confirms the server-reported off state',async()=>{
 vi.mocked(currentWebPush).mockResolvedValueOnce({browserSubscribed:true,id:'DEMO-current',enabled:true}).mockResolvedValueOnce({browserSubscribed:true,id:'DEMO-current',enabled:false});
 render(<PushNotificationSettings/>);const toggle=await screen.findByRole('switch',{name:'Receive Device Notifications'});fireEvent.click(toggle);
 await waitFor(()=>expect(disableWebPush).toHaveBeenCalledTimes(1));await waitFor(()=>expect(toggle.getAttribute('aria-checked')).toBe('false'));
 expect(await screen.findByText('Device notifications turned off.')).toBeTruthy();
});

it('explains missing local server configuration and keeps new subscription setup unavailable',async()=>{
 vi.mocked(api.pushConfig).mockResolvedValue({available:false,public_key:null,test_available:false});vi.mocked(currentWebPush).mockResolvedValue({browserSubscribed:false,id:null,enabled:false});
 render(<PushNotificationSettings/>);const toggle=await screen.findByRole('switch',{name:'Receive Device Notifications'});
 expect(toggle.getAttribute('aria-checked')).toBe('false');expect(toggle.hasAttribute('disabled')).toBe(true);
 expect(screen.getAllByText('This application is not configured for new device subscriptions.').length).toBe(2);
 const test=screen.getByRole('button',{name:'Test Notification'});expect(test.hasAttribute('disabled')).toBe(true);
 fireEvent.click(screen.getByRole('button',{name:/Notification Settings/}));expect(await screen.findByText('Requires application setup')).toBeTruthy();
 expect(screen.getByText(/Ask the application administrator to configure it/)).toBeTruthy();expect(Notification.requestPermission).not.toHaveBeenCalled();
});


it('distinguishes push configuration API errors from a confirmed unavailable capability',async()=>{
 vi.mocked(api.pushConfig).mockRejectedValue(new Error('DEMO config read failed'));
 vi.mocked(currentWebPush).mockResolvedValue({browserSubscribed:false,id:null,enabled:false});
 render(<PushNotificationSettings/>);
 expect((await screen.findAllByText('Could not check notification availability. Retry in Notification Settings.')).length).toBeGreaterThan(0);
 expect(screen.queryByText('This application is not configured for new device subscriptions.')).toBeNull();
 expect(screen.getByRole('switch',{name:'Receive Device Notifications'}).hasAttribute('disabled')).toBe(true);
 fireEvent.click(screen.getByRole('button',{name:/Notification Settings/}));
 expect((await screen.findAllByText('Could not check')).length).toBeGreaterThan(0);
});

it('retains the last confirmed device switch state when a later status read fails',async()=>{
 vi.mocked(currentWebPush).mockResolvedValueOnce({browserSubscribed:true,id:'DEMO-current',enabled:true}).mockRejectedValueOnce(new Error('DEMO current subscription read failed'));
 render(<PushNotificationSettings/>);
 const toggle=await screen.findByRole('switch',{name:'Receive Device Notifications'});
 expect(toggle.getAttribute('aria-checked')).toBe('true');
 await act(async()=>window.dispatchEvent(new Event('focus')));
 expect((await screen.findAllByText('Could not check this device subscription. Retry in Notification Settings.')).length).toBeGreaterThan(0);
 expect(toggle.getAttribute('aria-checked')).toBe('true');
 expect(screen.queryByText('Device subscription saved.')).toBeNull();
});

it('does not let account-device listing failures block a confirmed current-device change',async()=>{
 vi.mocked(api.pushSubscriptions).mockRejectedValue(new Error('DEMO account list unavailable'));
 vi.mocked(currentWebPush).mockResolvedValueOnce({browserSubscribed:false,id:null,enabled:false}).mockResolvedValueOnce({browserSubscribed:true,id:'DEMO-current',enabled:true});
 render(<PushNotificationSettings/>);
 const toggle=await screen.findByRole('switch',{name:'Receive Device Notifications'});
 expect(toggle.getAttribute('aria-checked')).toBe('false');fireEvent.click(toggle);
 await waitFor(()=>expect(enableWebPush).toHaveBeenCalledOnce());
 await waitFor(()=>expect(toggle.getAttribute('aria-checked')).toBe('true'));
 expect(await screen.findByText('Device subscription saved.')).toBeTruthy();
});

it('explains a denied browser permission and does not offer a test request',async()=>{
 vi.stubGlobal('Notification',{permission:'denied',requestPermission:vi.fn()});render(<PushNotificationSettings/>);
 expect(await screen.findByText('Notifications are blocked in your browser.')).toBeTruthy();
 expect(screen.getByRole('button',{name:'Test Notification'}).hasAttribute('disabled')).toBe(true);
 fireEvent.click(screen.getByRole('button',{name:/Notification Settings/}));expect((await screen.findAllByText('Notifications are blocked in your browser. Change site or device notification settings, then refresh this page.')).length).toBeGreaterThan(0);
 expect(Notification.requestPermission).not.toHaveBeenCalled();
});

it('enables the test action only after browser permission and sends without claiming receipt',async()=>{
 vi.mocked(currentWebPush).mockResolvedValue({browserSubscribed:true,id:'DEMO-current',enabled:true});
 vi.stubGlobal('Notification',{permission:'default',requestPermission:vi.fn()});render(<PushNotificationSettings/>);
 const send=await screen.findByRole('button',{name:'Test Notification'});
 expect(send.hasAttribute('disabled')).toBe(true);expect(screen.getByText('Allow browser notifications before sending a test.')).toBeTruthy();
 vi.stubGlobal('Notification',{permission:'granted',requestPermission:vi.fn()});cleanup();render(<PushNotificationSettings/>);
 fireEvent.click(await screen.findByRole('button',{name:'Test Notification'}));
 expect(await screen.findByText('The test was accepted by the service. Check this device; receipt is not confirmed.')).toBeTruthy();
 expect(api.testPush).toHaveBeenCalledWith('DEMO-current',expect.any(String));
 expect(screen.queryByText('You confirmed it arrived')).toBeNull();
});

it('keeps an existing subscription enabled when production supports setup but not direct test sending',async()=>{
 vi.mocked(api.pushConfig).mockResolvedValue({available:true,public_key:'DEMO',test_available:false});
 vi.mocked(currentWebPush).mockResolvedValue({browserSubscribed:true,id:'DEMO-current',enabled:true});
 render(<PushNotificationSettings/>);
 const toggle=await screen.findByRole('switch',{name:'Receive Device Notifications'});
 expect(toggle.getAttribute('aria-checked')).toBe('true');expect(toggle.hasAttribute('disabled')).toBe(false);
 const send=screen.getByRole('button',{name:'Test Notification'});
 expect(send.hasAttribute('disabled')).toBe(true);
 expect(screen.getByText('A test notification cannot be sent from this page. Device subscription is managed separately.')).toBeTruthy();
 expect(screen.queryByText('This application is not configured for new device subscriptions.')).toBeNull();
});

it('localises the separate test-sending limitation in Chinese',async()=>{
 function ChooseChinese(){const {setLanguage}=useLanguage();const changed=useRef(false);useEffect(()=>{if(!changed.current){changed.current=true;setLanguage('zh');}},[setLanguage]);return null;}
 vi.mocked(api.pushConfig).mockResolvedValue({available:true,public_key:'DEMO',test_available:false});
 vi.mocked(currentWebPush).mockResolvedValue({browserSubscribed:true,id:'DEMO-current',enabled:true});
 render(<LanguageProvider><ChooseChinese/><PushNotificationSettings/></LanguageProvider>);
 expect(await screen.findByText('\u6b64\u9875\u9762\u65e0\u6cd5\u53d1\u9001\u6d4b\u8bd5\u901a\u77e5\uff1b\u8bbe\u5907\u8ba2\u9605\u8bbe\u7f6e\u4e0d\u53d7\u5f71\u54cd\u3002')).toBeTruthy();
 expect(screen.getByRole('switch',{name:/\u63a5\u6536\u8bbe\u5907\u901a\u77e5/}).getAttribute('aria-checked')).toBe('true');
});

it('keeps test delivery available for a confirmed existing device when new subscriptions are unavailable',async()=>{
 vi.mocked(api.pushConfig).mockResolvedValue({available:false,public_key:null,test_available:true});
 render(<PushNotificationSettings/>);
 expect(await screen.findByText('This device is already subscribed. New device setup is currently unavailable.')).toBeTruthy();
 const send=await screen.findByRole('button',{name:'Test Notification'});expect(send.hasAttribute('disabled')).toBe(false);
 fireEvent.click(send);expect(await screen.findByText('The test was accepted by the service. Check this device; receipt is not confirmed.')).toBeTruthy();
});

it('lists real saved devices and refreshes after disabling an individual other device',async()=>{
 vi.mocked(api.pushSubscriptions).mockResolvedValueOnce([{id:'DEMO-current',enabled:true},{id:'DEMO-other',enabled:true}]).mockResolvedValueOnce([{id:'DEMO-current',enabled:true},{id:'DEMO-other',enabled:false}]);
 render(<PushNotificationSettings/>);fireEvent.click(await screen.findByRole('button',{name:/Notification Settings/}));
 fireEvent.click(screen.getByText(/Account devices/));
 expect(await screen.findByText('Device 1 · This device')).toBeTruthy();expect(screen.getByText('Device 2')).toBeTruthy();
 expect(screen.queryByText('DEMO-current')).toBeNull();expect(screen.queryByText('DEMO-other')).toBeNull();
 fireEvent.click(screen.getByRole('button',{name:'Turn off device 2'}));
 await waitFor(()=>expect(api.revokePushSubscription).toHaveBeenCalledWith('DEMO-other'));
 await waitFor(()=>expect(screen.getByText('Device 2').parentElement?.textContent).toContain('Off'));
 expect(screen.getByText('Use the device switch on the main page to manage this device.')).toBeTruthy();
});

it('requires explicit confirmation before disabling all account devices and verifies the result',async()=>{
 vi.mocked(api.pushSubscriptions).mockResolvedValueOnce([{id:'DEMO-current',enabled:true},{id:'DEMO-other',enabled:true}]).mockResolvedValueOnce([{id:'DEMO-current',enabled:false},{id:'DEMO-other',enabled:false}]);
 vi.mocked(currentWebPush).mockResolvedValueOnce({browserSubscribed:true,id:'DEMO-current',enabled:true}).mockResolvedValueOnce({browserSubscribed:false,id:null,enabled:false});
 render(<PushNotificationSettings/>);fireEvent.click(await screen.findByRole('button',{name:/Notification Settings/}));
 const disable=screen.getByRole('button',{name:'Disable all device notifications'});fireEvent.click(disable);
 expect(disableWebPush).not.toHaveBeenCalled();expect(screen.getByRole('group',{name:'Confirm account-wide disable'})).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'Confirm disable all devices'}));
 await waitFor(()=>expect(disableWebPush).toHaveBeenCalledWith(true));
 expect(await screen.findByText('Push notifications are off on all account devices.')).toBeTruthy();
});

it('reports possible partial completion accurately when account-wide disable fails',async()=>{
 vi.mocked(disableWebPush).mockRejectedValueOnce(new Error('DEMO second-device revoke failed'));
 render(<PushNotificationSettings/>);fireEvent.click(await screen.findByRole('button',{name:/Notification Settings/}));
 fireEvent.click(screen.getByRole('button',{name:'Disable all device notifications'}));
 fireEvent.click(screen.getByRole('button',{name:'Confirm disable all devices'}));
 expect(await screen.findByText('The all-device request did not complete. Some devices may already be off; refresh the list to confirm. Medication plans, adherence history, and reminder preferences are unchanged.')).toBeTruthy();
});

it('shows empty and failed account-device list states without invented entries or unsafe actions',async()=>{
 vi.mocked(api.pushSubscriptions).mockResolvedValueOnce([]).mockResolvedValueOnce([]);
 vi.mocked(currentWebPush).mockResolvedValue({browserSubscribed:false,id:null,enabled:false});
 render(<PushNotificationSettings/>);fireEvent.click(await screen.findByRole('button',{name:/Notification Settings/}));fireEvent.click(screen.getByText(/Account devices/));
 expect(await screen.findByText('No saved devices.')).toBeTruthy();expect(screen.getByRole('button',{name:'Disable all device notifications'}).hasAttribute('disabled')).toBe(true);
 cleanup();vi.mocked(api.pushSubscriptions).mockReset().mockRejectedValue(new Error('DEMO list error'));
 render(<PushNotificationSettings/>);fireEvent.click(await screen.findByRole('button',{name:/Notification Settings/}));fireEvent.click(screen.getByText(/Account devices/));
 expect(await screen.findByText('Could not load account devices. Refresh to try again.')).toBeTruthy();
 expect(screen.getByRole('button',{name:'Disable all device notifications'}).hasAttribute('disabled')).toBe(true);
});

it('shows device management labels and help in Chinese',async()=>{
 function ChooseChinese(){const {setLanguage}=useLanguage();const changed=useRef(false);useEffect(()=>{if(!changed.current){changed.current=true;setLanguage('zh');}},[setLanguage]);return null;}
 render(<LanguageProvider><ChooseChinese/><PushNotificationSettings/></LanguageProvider>);
 fireEvent.click(await screen.findByRole('button',{name:/通知设置/}));
 expect(await screen.findByRole('heading',{name:'当前设备'})).toBeTruthy();expect(screen.getByText(/账户设备/)).toBeTruthy();
 fireEvent.click(screen.getByText('设备通知帮助'));
 fireEvent.change(screen.getByRole('combobox'),{target:{value:'iOS'}});
 expect(screen.getByText(/请使用 iOS\/iPadOS 16.4/)).toBeTruthy();
 fireEvent.click(screen.getByText('故障排查'));expect(screen.getByText('浏览器权限')).toBeTruthy();
});

it('offers all four platform guides in advanced settings',()=>{
 render(<NotificationGuide/>);fireEvent.click(screen.getByText('Device notification guide'));
 fireEvent.change(screen.getByRole('combobox'),{target:{value:'iOS'}});
 expect(screen.getByText(/Use iOS\/iPadOS 16.4/)).toBeTruthy();expect(screen.getAllByRole('option').map(option=>option.textContent)).toEqual(['Windows','Android','iPhone / iPad','macOS']);
});

it('activation invitation remains optional and opening it never asks notification permission',async()=>{
 const open=vi.fn();const mounted=render(<NotificationInvitation ownerId="DEMO-A" onSettings={open}/>);
 expect(screen.queryByText('Your medication plan is ready')).toBeNull();
 await act(async()=>{window.dispatchEvent(new Event('pharmascan:plan-activated'));});expect(screen.getByText('Your medication plan is ready')).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'Later'}));mounted.rerender(<NotificationInvitation ownerId="DEMO-B" onSettings={open}/>);
 await act(async()=>{window.dispatchEvent(new Event('pharmascan:plan-activated'));});
 fireEvent.click(screen.getByRole('button',{name:'Set Up Device Notifications'}));expect(open).toHaveBeenCalledOnce();
 expect(enableWebPush).not.toHaveBeenCalled();expect(Notification.requestPermission).not.toHaveBeenCalled();
});
