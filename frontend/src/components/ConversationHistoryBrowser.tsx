import {useEffect,useRef,useState} from 'react';
import {api,type ConversationEntry} from '../api/client';
import {conversationDateGroups} from '../conversationDates';
import {useLanguage} from '../language';
import {ErrorNotice} from './primitives';

/** The current API exposes saved exchanges, not restorable agent session IDs. */
export function ConversationHistoryBrowser({revision,onBack}:{revision:number;onBack:()=>void}){
 const {t,language,preferences}=useLanguage();
 const [rows,setRows]=useState<ConversationEntry[]>([]),[cursor,setCursor]=useState<string|null>(null);
 const [error,setError]=useState<unknown>(null),[loading,setLoading]=useState(true),[retry,setRetry]=useState(0);
 const [selected,setSelected]=useState<ConversationEntry|null>(null),[now,setNow]=useState(()=>new Date());
 const root=useRef<HTMLElement>(null);
 useEffect(()=>{root.current?.focus();},[selected]);
 useEffect(()=>{const timer=setInterval(()=>setNow(new Date()),60000);return()=>clearInterval(timer);},[]);
 useEffect(()=>{let live=true;setLoading(true);setError(null);void api.conversationHistory().then(page=>{if(live){setRows(page.entries);setCursor(page.next_before);}}).catch(caught=>{if(live)setError(caught);}).finally(()=>{if(live)setLoading(false);});return()=>{live=false;};},[revision,retry]);
 // A paginated read must not update an unmounted history view.
 const [pageBefore,setPageBefore]=useState<string|null>(null);
 useEffect(()=>{if(!pageBefore)return;let live=true;setLoading(true);setError(null);void api.conversationHistory(pageBefore).then(page=>{if(live){setRows(previous=>[...previous,...page.entries.filter(row=>!previous.some(old=>old.id===row.id))]);setCursor(page.next_before);}}).catch(caught=>{if(live)setError(caught);}).finally(()=>{if(live){setLoading(false);setPageBefore(null);}});return()=>{live=false;};},[pageBefore]);
 const time=(stamp:string)=>Number.isFinite(Date.parse(stamp))?new Date(stamp).toLocaleString(language==='zh'?'zh-SG':'en-SG',{timeZone:preferences.timezone}):t('Date unavailable');
 return <section ref={root} tabIndex={-1} className="conversation-history-browser" aria-label={t('Saved messages')}>
  <button onClick={onBack}>{t('Back to current conversation')}</button>
  <p className="notice">{t('Saved questions and answers can be viewed here. Return to your current conversation to continue chatting.')}</p>
  {selected?<article className="history-message"><button onClick={()=>setSelected(null)}>{t('Back to history list')}</button><time>{time(selected.created_at)}</time><p className="user-message">{selected.user_text}</p><p>{selected.assistant_text}</p></article>:<>
   {error?<><ErrorNotice error={error}/><button disabled={loading} onClick={()=>setRetry(value=>value+1)}>{t('Try again')}</button></>:null}
   {loading?<p role="status">{t('Loading conversations…')}</p>:null}
   {!loading&&!error&&!rows.length?<p>{t(preferences.conversation_history_enabled?'No saved conversations yet.':'Saving is off. No saved messages are available.')}</p>:null}
   {conversationDateGroups(rows,preferences.timezone,now).map(group=><section key={group.date} className="history-date-group"><h2>{group.relative?t(group.relative):group.date==='unknown'?t('Date unavailable'):group.date}</h2>{group.rows.map(row=><button className="history-entry" key={row.id} onClick={()=>setSelected(row)}><span>{row.user_text.slice(0,120)}</span><time>{time(row.created_at)}</time></button>)}</section>)}
   {cursor?<button disabled={loading} onClick={()=>setPageBefore(cursor)}>{t('Load earlier conversations')}</button>:null}
  </>}
 </section>;
}
