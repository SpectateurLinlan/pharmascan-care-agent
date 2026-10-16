// @vitest-environment jsdom
// LOCAL/MOCK: no external push endpoint is contacted.
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {act,cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {api} from '../api/client';
import {currentWebPush,disableWebPush,enableWebPush} from '../webPush';
import {PushNotificationSettings,NotificationGuide} from './PushNotificationSettings';
import {NotificationInvitation} from './NotificationInvitation';

vi.mock('../api/client',()=>({ApiError:class extends Error{},api:{pushConfig:vi.fn(),pushSubscriptions:vi.fn(),testPush:vi.fn(),revokePushSubscription:vi.fn()}}));
vi.mock('../webPush',()=>({pushSupported:()=>true,currentWebPush:vi.fn(),disableWebPush:vi.fn(),enableWebPush:vi.fn()}));
beforeEach(()=>{
 vi.stubGlobal('Notification',{permission:'default',requestPermission:vi.fn()});
 vi.mocked(api.pushConfig).mockResolvedValue({available:true,public_key:'DEMO',test_available:true});
 vi.mocked(api.pushSubscriptions).mockResolvedValue([{id:'DEMO-current',enabled:true},{id:'DEMO-other',enabled:true}]);
 vi.mocked(currentWebPush).mockResolvedValue({browserSubscribed:true,id:'DEMO-current',enabled:true});
 vi.mocked(api.testPush).mockResolvedValue({status:'sent'});
 vi.mocked(disableWebPush).mockResolvedValue();vi.mocked(enableWebPush).mockResolvedValue();
});
afterEach(()=>{cleanup();localStorage.clear();vi.resetAllMocks();vi.unstubAllGlobals();});

it('reads status without requesting permission, and separates test acceptance from receipt',async()=>{
 render(<PushNotificationSettings/>);
 const test=await screen.findByRole('button',{name:'Send test notification'});
 await waitFor(()=>expect(test.hasAttribute('disabled')).toBe(false));
 expect(Notification.requestPermission).not.toHaveBeenCalled();expect(enableWebPush).not.toHaveBeenCalled();
 fireEvent.click(test);
 await screen.findByText('The push service accepted the test. Check your device; receipt has not been verified.');
 expect(api.testPush).toHaveBeenCalledWith('DEMO-current',expect.any(String));
 expect(screen.getByText('Not verified on this device')).toBeTruthy();
});
it('failed test never claims acceptance, and a different device is revoked by its own id',async()=>{
 vi.mocked(api.testPush).mockResolvedValue({status:'uncertain_delivery'});
 render(<PushNotificationSettings/>);
 await waitFor(()=>expect(screen.getByRole('button',{name:'Send test notification'}).hasAttribute('disabled')).toBe(false));
 fireEvent.click(screen.getByRole('button',{name:'Send test notification'}));
 await screen.findByRole('alert');
 expect(screen.queryByText('The push service accepted the test. Check your device; receipt has not been verified.')).toBeNull();
 fireEvent.click(screen.getByRole('button',{name:'Disable device 2'}));
 await waitFor(()=>expect(api.revokePushSubscription).toHaveBeenCalledWith('DEMO-other'));
});
it('disables only the current device and can explicitly enable again',async()=>{
 render(<PushNotificationSettings/>);await screen.findByRole('button',{name:'Disable device 1'});
 fireEvent.click(screen.getByRole('button',{name:'Turn off this device'}));
 await waitFor(()=>expect(disableWebPush).toHaveBeenCalledWith());
 await screen.findByText('This device subscription is off. Browser permission is unchanged.');
 fireEvent.click(screen.getByRole('button',{name:'Enable on this device'}));
 await waitFor(()=>expect(enableWebPush).toHaveBeenCalled());
});
it('failed status cannot be presented as a saved subscription',async()=>{
 vi.mocked(api.pushSubscriptions).mockRejectedValue(new Error('DEMO unavailable'));
 render(<PushNotificationSettings/>);await screen.findByRole('alert');
 expect(screen.getByText('Device status has not been checked. Refresh to retry.')).toBeTruthy();
 expect(screen.getByRole('button',{name:'Send test notification'}).hasAttribute('disabled')).toBe(true);
});
it('offers all four platform guides with iOS installation conditions',()=>{
 render(<NotificationGuide/>);
 fireEvent.click(screen.getByText('Device notification guide'));
 fireEvent.change(screen.getByRole('combobox'),{target:{value:'iOS'}});
 expect(screen.getByText(/Use iOS\/iPadOS 16.4/)).toBeTruthy();
 expect(screen.getAllByRole('option').map(option=>option.textContent)).toEqual(['Windows','Android','iOS','macOS']);
});
it('activation invitation is optional and once per owner; opening it never asks permission',async()=>{
 const open=vi.fn();const mounted=render(<NotificationInvitation ownerId="DEMO-A" onSettings={open}/>);
 expect(screen.queryByText('Your medication plan is ready')).toBeNull();
 await act(async()=>{window.dispatchEvent(new Event('pharmascan:plan-activated'));});
 expect(screen.getByText('Your medication plan is ready')).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'Later'}));
 await act(async()=>{window.dispatchEvent(new Event('pharmascan:plan-activated'));});
 expect(screen.queryByText('Your medication plan is ready')).toBeNull();
 mounted.rerender(<NotificationInvitation ownerId="DEMO-B" onSettings={open}/>);
 await act(async()=>{window.dispatchEvent(new Event('pharmascan:plan-activated'));});
 fireEvent.click(screen.getByRole('button',{name:'View notification guide'}));expect(open).toHaveBeenCalledOnce();
 expect(enableWebPush).not.toHaveBeenCalled();expect(Notification.requestPermission).not.toHaveBeenCalled();
});
