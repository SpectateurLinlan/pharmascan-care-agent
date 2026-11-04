// @vitest-environment jsdom
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor,within} from '@testing-library/react';
import {api} from '../api/client';
import type {WorkflowView} from '../api/assistantWorkflows';
import * as push from '../webPush';
import {AssistantWorkflow} from './AssistantWorkflow';
vi.mock('../webPush',()=>({pushSupported:vi.fn().mockReturnValue(true),currentWebPush:vi.fn(),enableWebPush:vi.fn(),disableWebPush:vi.fn()}));
const current={browserSubscribed:false,id:null,enabled:false};
const base:WorkflowView={task_id:'DEMO-device-task',revision:1,capability_id:'notification.subscribe',state:'collecting',save_mode:'allowed',storage_state:'saved',prompt_key:'assistant.notification.device',input_fields:{},visible_fields:{operation:'subscribe',test_send_allowed:false},missing_fields:[],actions:[{kind:'device',action:'notification_permission'}],explanations:[],result_ref:null};
beforeEach(()=>{vi.spyOn(api,'pushConfig').mockResolvedValue({available:true,public_key:'BA',test_available:true});vi.spyOn(api,'pushSubscriptions').mockResolvedValue([]);vi.mocked(push.currentWebPush).mockResolvedValue(current);vi.stubGlobal('Notification',{permission:'granted',requestPermission:vi.fn()});});
afterEach(()=>{cleanup();vi.restoreAllMocks();vi.clearAllMocks();vi.unstubAllGlobals();});
async function open(view:WorkflowView=base,onEvent=vi.fn()){render(<AssistantWorkflow view={view} busy={false} onEvent={onEvent}/>);fireEvent.click(await screen.findByRole('button',{name:'Open device notification action'}));await screen.findByRole('button',{name:'Confirm enable on this device'});}

it('does not read devices or request permission until the scoped controls are explicitly opened',async()=>{
 render(<AssistantWorkflow view={base} busy={false} onEvent={vi.fn()}/>);await screen.findByRole('button',{name:'Open device notification action'});expect(api.pushConfig).not.toHaveBeenCalled();expect(push.currentWebPush).not.toHaveBeenCalled();expect(push.enableWebPush).not.toHaveBeenCalled();
});
it('enables only on independent confirmation and verifies the actual native state',async()=>{
 const send=vi.fn();await open(base,send);expect(push.enableWebPush).not.toHaveBeenCalled();vi.mocked(push.currentWebPush).mockResolvedValue({browserSubscribed:true,id:'DEMO-private-subscription',enabled:true});
 fireEvent.click(screen.getByRole('button',{name:'Confirm enable on this device'}));await waitFor(()=>expect(push.enableWebPush).toHaveBeenCalledWith(expect.objectContaining({available:true}),expect.objectContaining({binding:{task_id:base.task_id,expected_revision:1},isCurrent:expect.any(Function)})));
 expect(await screen.findByText('Device subscription saved. Delivery has not been verified.')).toBeTruthy();expect(send).not.toHaveBeenCalled();
});
it('keeps failures visible and checks actual status without automatically repeating a subscription',async()=>{
 await open();vi.mocked(push.enableWebPush).mockRejectedValueOnce(new Error('DEMO failed save'));fireEvent.click(screen.getByRole('button',{name:'Confirm enable on this device'}));expect(await screen.findByRole('alert')).toBeTruthy();
 vi.mocked(push.currentWebPush).mockResolvedValue({browserSubscribed:true,id:'DEMO-private-subscription',enabled:true});fireEvent.click(screen.getByRole('button',{name:'Refresh device status'}));expect(await screen.findByText('This device is subscribed; delivery has not been verified.')).toBeTruthy();expect(push.enableWebPush).toHaveBeenCalledTimes(1);
});
it('requires separate explicit all-device scope before revoking account devices',async()=>{
 vi.mocked(api.pushSubscriptions).mockResolvedValue([{id:'DEMO-private-1',enabled:true},{id:'DEMO-private-2',enabled:true}]);
 render(<AssistantWorkflow view={{...base,capability_id:'notification.unsubscribe'}} busy={false} onEvent={vi.fn()}/>);fireEvent.click(await screen.findByRole('button',{name:'Open device notification action'}));await screen.findByRole('combobox',{name:'Turn off notifications for'});
 fireEvent.change(screen.getByRole('combobox',{name:'Turn off notifications for'}),{target:{value:'all'}});expect(push.disableWebPush).not.toHaveBeenCalled();vi.mocked(api.pushSubscriptions).mockResolvedValue([{id:'DEMO-private-1',enabled:false},{id:'DEMO-private-2',enabled:false}]);fireEvent.click(screen.getByRole('button',{name:'Confirm turn off notifications'}));await waitFor(()=>expect(push.disableWebPush).toHaveBeenCalledWith(true,expect.objectContaining({allowAllDevices:true,binding:{task_id:base.task_id,expected_revision:1}})));
});
it('keeps tests disabled without workflow send approval even if native configuration is ready',async()=>{
 vi.mocked(push.currentWebPush).mockResolvedValue({browserSubscribed:true,id:'DEMO-private-subscription',enabled:true});const send=vi.spyOn(api,'testPush');
 render(<AssistantWorkflow view={{...base,capability_id:'notification.test'}} busy={false} onEvent={vi.fn()}/>);fireEvent.click(await screen.findByRole('button',{name:'Open device notification action'}));expect(await screen.findByText('Sending a test notification has not been authorized for this workflow.')).toBeTruthy();expect(screen.getByRole('button',{name:'Confirm send one test notification'})).toHaveProperty('disabled',true);expect(send).not.toHaveBeenCalled();
});
it('never retries an approved test after an uncertain response and sends no native IDs to workflow events',async()=>{
 vi.mocked(push.currentWebPush).mockResolvedValue({browserSubscribed:true,id:'DEMO-private-subscription',enabled:true});const send=vi.spyOn(api,'testPush').mockRejectedValue(new Error('DEMO unknown outcome')),event=vi.fn();
 render(<AssistantWorkflow view={{...base,capability_id:'notification.test',visible_fields:{test_send_allowed:true}}} busy={false} onEvent={event}/>);fireEvent.click(await screen.findByRole('button',{name:'Open device notification action'}));const button=await screen.findByRole('button',{name:'Confirm send one test notification'});await waitFor(()=>expect(button).toHaveProperty('disabled',false));fireEvent.click(button);expect(await screen.findByRole('alert')).toBeTruthy();expect(button).toHaveProperty('disabled',true);expect(send).toHaveBeenCalledWith('DEMO-private-subscription',expect.any(String),{task_id:base.task_id,expected_revision:1});expect(event).not.toHaveBeenCalled();
});
it('does not expose device mutation controls in no-save mode',async()=>{
 render(<AssistantWorkflow view={{...base,save_mode:'ephemeral',storage_state:'ephemeral'}} busy={false} onEvent={vi.fn()}/>);expect(await screen.findByText('Save this task before changing device notifications.')).toBeTruthy();expect(screen.queryByRole('button',{name:'Open device notification action'})).toBeNull();expect(api.pushConfig).not.toHaveBeenCalled();
});
it('cancel closes the independent sheet without a native action',async()=>{await open();fireEvent.click(within(screen.getByRole('dialog')).getByRole('button',{name:'Cancel'}));expect(screen.queryByRole('dialog')).toBeNull();expect(push.enableWebPush).not.toHaveBeenCalled();});
it('explains missing push configuration even when the saved device list cannot be read',async()=>{
 vi.mocked(api.pushConfig).mockResolvedValue({available:false,public_key:null,test_available:false});vi.mocked(api.pushSubscriptions).mockRejectedValue(new Error('DEMO subscriptions unavailable'));
 render(<AssistantWorkflow view={base} busy={false} onEvent={vi.fn()}/>);fireEvent.click(await screen.findByRole('button',{name:'Open device notification action'}));expect(await screen.findByText('Background notifications are not configured for this application.')).toBeTruthy();expect(push.enableWebPush).not.toHaveBeenCalled();
});
