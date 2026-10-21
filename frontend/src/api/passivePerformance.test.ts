import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import {expect,it,vi} from 'vitest';

const script=readFileSync(new URL('../../../scripts/qa/performance_in_browser.js',import.meta.url),'utf8');
function setup(origin='http://localhost:5173'){
 let now=10;
 let observe!:(list:{getEntries:()=>unknown[]})=>void;
 const disconnect=vi.fn(),fetch=vi.fn(),info=vi.fn();
 const window:Record<string,unknown>={fetch};
 const context={window,location:{origin,href:origin+'/'},performance:{now:()=>now},URL,console:{info},
  PerformanceObserver:class{constructor(callback:typeof observe){observe=callback;}observe(){}disconnect(){disconnect();}}};
 runInNewContext(script,context);
 type Diagnostic={summary:()=>{endpoints:Array<Record<string,unknown>>};stop:()=>unknown};
 return {window,fetch,info,disconnect,diagnostic:window.medithreadPerformance as Diagnostic,
  advance:(value:number)=>{now+=value;},resource:(entry:unknown)=>observe({getEntries:()=>[entry]})};
}

it('observes only normal requests without initiating any, reading bodies or exporting credentials',async()=>{
 const h=setup();expect(h.fetch).not.toHaveBeenCalled();
 const json=vi.fn();let finish!:(response:unknown)=>void;
 h.fetch.mockReturnValue(new Promise(resolve=>{finish=resolve;}));
 const response={status:200,json};
 const fetch=h.window.fetch as typeof globalThis.fetch;
 const pending=fetch('/api/me/dose-follow-ups?client_id=PRIVATE',{headers:{Authorization:'PRIVATE'}});
 expect(h.diagnostic.summary().endpoints[0]).toMatchObject({fetch_calls:1,pending:1,max_simultaneous_fetches:1});
 h.advance(15000);finish(response);expect(await pending).toBe(response);
 h.resource({name:'http://localhost:5173/api/me/dose-follow-ups?client_id=PRIVATE',startTime:11,duration:15000,requestStart:12,responseStart:15010,responseEnd:15011,
  serverTiming:[{name:'auth',duration:200},{name:'data',duration:14000},{name:'data_calls',description:'35'},{name:'PRIVATE',duration:99}]});
 const summary=h.diagnostic.summary();
 expect(summary.endpoints[0]).toMatchObject({pending:0,network_requests:1,server_timing:{data_calls:{median:35},data:{median:14000}}});
 expect(JSON.stringify(summary)).not.toContain('PRIVATE');expect(json).not.toHaveBeenCalled();
 h.diagnostic.stop();expect(h.window.fetch).toBe(h.fetch);expect(h.disconnect).toHaveBeenCalledOnce();
});

it('keeps failures and overlap visible without exposing error text',async()=>{
 const h=setup();let fail!:(error:Error)=>void;
 h.fetch.mockReturnValue(new Promise((_,reject)=>{fail=reject;}));
 const fetch=h.window.fetch as typeof globalThis.fetch;
 const pending=Promise.allSettled([fetch('/api/reminders/alerts'),fetch('/api/reminders/alerts')]);
 expect(h.diagnostic.summary().endpoints[1]).toMatchObject({pending:2,max_simultaneous_fetches:2});
 h.advance(5000);fail(new Error('PRIVATE provider details'));await pending;
 const summary=h.diagnostic.summary();expect(summary.endpoints[1]).toMatchObject({pending:0,status_counts:{network_failure:2}});
 expect(JSON.stringify(summary)).not.toContain('PRIVATE');
});

it('refuses nonlocal origins and ignores unrelated or external endpoints',async()=>{
 expect(()=>setup('https://example.com')).toThrow('Run only');
 const h=setup();h.fetch.mockResolvedValue({status:200});
 const fetch=h.window.fetch as typeof globalThis.fetch;
 await fetch('https://example.com/api/reminders/alerts');await fetch('/api/agent/messages');
 expect(h.diagnostic.summary().endpoints.every(row=>row.fetch_calls===0)).toBe(true);
});
