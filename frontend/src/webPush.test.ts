// @vitest-environment jsdom
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {api} from './api/client';
import {currentWebPush,disableWebPush,enableWebPush} from './webPush';
vi.mock('./api/client',()=>({api:{currentPush:vi.fn(),pushConfig:vi.fn(),savePushSubscription:vi.fn(),revokeCurrentPush:vi.fn(),pushSubscriptions:vi.fn(),revokePushSubscription:vi.fn()}}));
const subscription={toJSON:()=>({endpoint:'https://fcm.googleapis.com/DEMO',keys:{auth:'DEMO-auth',p256dh:'DEMO-key'}}),unsubscribe:vi.fn().mockResolvedValue(true)};
const manager={getSubscription:vi.fn(),subscribe:vi.fn()};
const registration={pushManager:manager};
const permission=vi.fn();
beforeEach(()=>{
 vi.stubGlobal('isSecureContext',true);vi.stubGlobal('PushManager',class{});vi.stubGlobal('Notification',{requestPermission:permission});
 Object.defineProperty(navigator,'serviceWorker',{configurable:true,value:{register:vi.fn().mockResolvedValue(registration),ready:Promise.resolve(registration),getRegistration:vi.fn().mockResolvedValue(registration)}});
 manager.getSubscription.mockResolvedValue(null);manager.subscribe.mockResolvedValue(subscription);permission.mockResolvedValue('granted');
 vi.mocked(api.pushConfig).mockResolvedValue({available:false,public_key:null});vi.mocked(api.savePushSubscription).mockResolvedValue({id:'DEMO-sub',enabled:true});
});
afterEach(()=>{vi.clearAllMocks();vi.unstubAllGlobals();});
it('does not request system permission when the server is not configured',async()=>{await expect(enableWebPush()).rejects.toThrow('not configured');expect(permission).not.toHaveBeenCalled();expect(manager.subscribe).not.toHaveBeenCalled();});
it('denied permission never subscribes or claims success',async()=>{permission.mockResolvedValue('denied');await expect(enableWebPush({available:true,public_key:'BA'})).rejects.toThrow('not granted');expect(api.savePushSubscription).not.toHaveBeenCalled();});
it('explicit enable uses a service worker and saves only subscription business fields',async()=>{await enableWebPush({available:true,public_key:'BA'});expect(manager.subscribe).toHaveBeenCalledWith({userVisibleOnly:true,applicationServerKey:expect.any(Uint8Array)});expect(api.savePushSubscription).toHaveBeenCalledWith(subscription.toJSON());});
it('server persistence failure is not represented as subscription success',async()=>{vi.mocked(api.savePushSubscription).mockRejectedValueOnce(new Error('DEMO unavailable'));await expect(enableWebPush({available:true,public_key:'BA'})).rejects.toThrow('unavailable');});
it('revokes the current server subscription before browser unsubscribe',async()=>{manager.getSubscription.mockResolvedValue(subscription);await disableWebPush();expect(api.revokeCurrentPush).toHaveBeenCalledWith(subscription.toJSON());expect(subscription.unsubscribe).toHaveBeenCalledOnce();});
it('revocation failure prevents claiming a completed logout cleanup',async()=>{manager.getSubscription.mockResolvedValue(subscription);vi.mocked(api.revokeCurrentPush).mockRejectedValueOnce(new Error('DEMO unavailable'));await expect(disableWebPush()).rejects.toThrow();expect(subscription.unsubscribe).not.toHaveBeenCalled();});
it('turning off other devices does not depend on browser Push support',async()=>{Object.defineProperty(navigator,'serviceWorker',{configurable:true,value:undefined});Reflect.deleteProperty(navigator,'serviceWorker');vi.mocked(api.pushSubscriptions).mockResolvedValue([{id:'DEMO-sub',enabled:true}]);await disableWebPush(true);expect(api.revokePushSubscription).toHaveBeenCalledWith('DEMO-sub');});
it('denied browser permission is never repeatedly requested',async()=>{vi.stubGlobal('Notification',{permission:'denied',requestPermission:permission});await expect(enableWebPush({available:true,public_key:'BA'})).rejects.toThrow('blocked');expect(permission).not.toHaveBeenCalled();});
it('status reads do not register, enable or request permission',async()=>{manager.getSubscription.mockResolvedValue(subscription);vi.mocked(api.currentPush).mockResolvedValue({id:'DEMO-sub',enabled:false});expect(await currentWebPush()).toEqual({id:'DEMO-sub',enabled:false,browserSubscribed:true});expect(permission).not.toHaveBeenCalled();expect(api.savePushSubscription).not.toHaveBeenCalled();});
