/** LOCAL/MOCK event tests; these do not prove actual Push delivery or device receipt. */
import {readFileSync} from 'node:fs';
import {expect,it,vi} from 'vitest';

interface WorkerEvent {data?:{json:()=>unknown};notification?:{close:()=>void};waitUntil:(work:Promise<unknown>)=>void}
function worker(){
 const handlers:Record<string,(event:WorkerEvent)=>void>={};
 const showNotification=vi.fn().mockResolvedValue(undefined),openWindow=vi.fn().mockResolvedValue(undefined);
 const scope={addEventListener:(name:string,handler:(event:WorkerEvent)=>void)=>{handlers[name]=handler;},location:{origin:'https://demo.example.invalid'},registration:{showNotification},clients:{matchAll:async()=>[],openWindow,claim:async()=>undefined},skipWaiting:()=>undefined};
 // Evaluate our own committed worker source, never user-supplied content.
 new Function('self',readFileSync(new URL('../public/sw.js',import.meta.url),'utf8'))(scope);
 return {handlers,showNotification,openWindow};
}
it('ignores untrusted message text and uses a fixed private Chinese body',async()=>{
 const {handlers,showNotification}=worker();let pending:Promise<unknown>=Promise.resolve();
 handlers.push!({data:{json:()=>({language:'zh',body:'DEMO private medicine must not appear',url:'https://evil.invalid'})},waitUntil:work=>{pending=work;}});await pending;
 expect(showNotification).toHaveBeenCalledWith('MediThread',expect.objectContaining({body:'请查看您的用药计划。',data:{url:'/#today'}}));
 expect(JSON.stringify(showNotification.mock.calls)).not.toContain('private medicine');
});
it('malformed payload still yields a private generic notification',async()=>{
 const {handlers,showNotification}=worker();let pending:Promise<unknown>=Promise.resolve();
 handlers.push!({data:{json:()=>{throw new Error('DEMO malformed');}},waitUntil:work=>{pending=work;}});await pending;
 expect(showNotification).toHaveBeenCalledWith('MediThread',expect.objectContaining({body:"It's time to check your medication plan."}));
});
it('notification click opens only the fixed authenticated app path',async()=>{
 const {handlers,openWindow}=worker();let pending:Promise<unknown>=Promise.resolve();
 handlers.notificationclick!({notification:{close:vi.fn()},waitUntil:work=>{pending=work;}});await pending;
 expect(openWindow).toHaveBeenCalledWith('https://demo.example.invalid/#today');
});
