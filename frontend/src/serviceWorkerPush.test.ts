// LOCAL/MOCK SW event execution; does not claim browser/provider delivery.
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import {expect,it,vi} from 'vitest';

it('uses generic bilingual content and a fixed same-origin authenticated app link',async()=>{
 const handlers:Record<string,(event:unknown)=>void>={};
 const show=vi.fn().mockResolvedValue(undefined),navigate=vi.fn().mockResolvedValue(undefined),focus=vi.fn();
 const openWindow=vi.fn();const client={url:'https://demo.invalid/#records',navigate,focus};
 const context={URL,self:{addEventListener:(name:string,handler:(event:unknown)=>void)=>{handlers[name]=handler;},
  location:{origin:'https://demo.invalid'},registration:{showNotification:show},clients:{matchAll:async()=>[client],openWindow}}};
 runInNewContext(readFileSync(new URL('../public/sw.js',import.meta.url),'utf8'),context);
 let pending:Promise<unknown>=Promise.resolve();
 if(!handlers.push||!handlers.notificationclick)throw new Error('Service worker handlers were not registered');
 handlers.push({data:{json:()=>({language:'zh',purpose:'test',url:'https://evil.invalid'})},waitUntil:(value:Promise<unknown>)=>{pending=value;}});
 await pending;expect(show.mock.calls[0]?.[1]?.body).toBe('这是一条测试通知。');
 expect(show.mock.calls[0]?.[1]?.data.url).toBe('/#today');
 handlers.notificationclick({notification:{close:vi.fn(),data:{url:'https://evil.invalid'}},waitUntil:(value:Promise<unknown>)=>{pending=value;}});
 await pending;expect(navigate).toHaveBeenCalledWith('https://demo.invalid/#today');expect(focus).toHaveBeenCalledOnce();expect(openWindow).not.toHaveBeenCalled();
});
