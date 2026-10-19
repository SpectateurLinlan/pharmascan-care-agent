import {Icon} from './Icon';
import {useEffect,useState} from 'react';
import {api,type ConversationEntry,type ConversationSummary} from '../api/client';
import {conversationDateGroups,localDateKey} from '../conversationDates';
import {useLanguage} from '../language';
import {ErrorNotice} from './primitives';

/** Stable conversations resume through their public API; unlinked legacy exchanges stay read-only. */
export function ConversationHistoryBrowser({revision,onSelect,selectedId,onConversationSelect,conversationId,onNew,disabled=false}:{revision:number;onSelect:(entry:ConversationEntry)=>void;selectedId?:string|null;onConversationSelect?:(id:string)=>void;conversationId?:string|null;onNew?:()=>void;disabled?:boolean}){
 const {t,language,preferences}=useLanguage();
 const [rows,setRows]=useState<ConversationEntry[]>([]),[cursor,setCursor]=useState<string|null>(null);
 const [threads,setThreads]=useState<ConversationSummary[]>([]),[threadCursor,setThreadCursor]=useState<string|null>(null);
 const [error,setError]=useState<unknown>(null),[loading,setLoading]=useState(true),[retry,setRetry]=useState(0);
 const [now,setNow]=useState(()=>new Date());
 useEffect(()=>{const timer=setInterval(()=>setNow(new Date()),60000);return()=>clearInterval(timer);},[]);
 useEffect(()=>{if(!api.conversations)return;let live=true;void api.conversations().then(page=>{if(live){setThreads(page.entries);setThreadCursor(page.next_before);}}).catch(caught=>{if(live)setError(caught);});return()=>{live=false;};},[revision,retry]);
 useEffect(()=>{let live=true;setLoading(true);setError(null);void api.conversationHistory().then(page=>{if(live){setRows(page.entries);setCursor(page.next_before);}}).catch(caught=>{if(live)setError(caught);}).finally(()=>{if(live)setLoading(false);});return()=>{live=false;};},[revision,retry]);
 const [pageBefore,setPageBefore]=useState<string|null>(null);
 useEffect(()=>{if(!pageBefore)return;let live=true;setLoading(true);setError(null);void api.conversationHistory(pageBefore).then(page=>{if(live){setRows(previous=>[...previous,...page.entries.filter(row=>!previous.some(old=>old.id===row.id))]);setCursor(page.next_before);}}).catch(caught=>{if(live)setError(caught);}).finally(()=>{if(live){setLoading(false);setPageBefore(null);}});return()=>{live=false;};},[pageBefore]);
 const time=(stamp:string)=>Number.isFinite(Date.parse(stamp))?new Date(stamp).toLocaleString(language==='zh'?'zh-SG':'en-SG',{timeZone:preferences.timezone}):t('Date unavailable');
 return <aside id="assistant-conversation-history" className="conversation-history-browser" aria-label={t('Saved messages')}>
  {onNew?<button className="history-new" disabled={disabled} onClick={onNew}><Icon name="plus"/>{t('New conversation')}</button>:null}
  <h2>{t('Conversation history')}</h2>
  <p>{t('Saved conversations can be reopened and continued. Older unlinked exchanges remain read-only.')}</p>
  {threads.map((thread,index)=><section key={thread.id} className="history-date-group">{index===0||localDateKey(threads[index-1]!.updated_at,preferences.timezone)!==localDateKey(thread.updated_at,preferences.timezone)?<h3>{localDateKey(thread.updated_at,preferences.timezone)===localDateKey(now.toISOString(),preferences.timezone)?t('Today'):localDateKey(thread.updated_at,preferences.timezone)}</h3>:null}<button className="history-entry" data-conversation-id={thread.id} disabled={disabled} aria-pressed={conversationId===thread.id} onClick={()=>onConversationSelect?.(thread.id)}><span>{thread.title}</span><time>{time(thread.updated_at)}</time></button></section>)}
  {threadCursor?<button disabled={loading} onClick={async()=>{setLoading(true);try{const page=await api.conversations(threadCursor);setThreads(previous=>[...previous,...page.entries.filter(row=>!previous.some(old=>old.id===row.id))]);setThreadCursor(page.next_before);}catch(caught){setError(caught);}finally{setLoading(false);}}}>{t('Load earlier conversations')}</button>:null}
  {error?<><ErrorNotice error={error}/><button disabled={loading} onClick={()=>setRetry(value=>value+1)}>{t('Try again')}</button></>:null}
  {loading?<p role="status">{t('Loading conversations...')}</p>:null}
  {!loading&&!error&&!rows.length&&!threads.length?<p>{t(preferences.conversation_history_enabled?'No saved conversations yet.':'Saving is off. No saved messages are available.')}</p>:null}
  {rows.length?<h3>{t('Older exchanges (read-only)')}</h3>:null}
  {conversationDateGroups(rows,preferences.timezone,now).map(group=><section key={group.date} className="history-date-group"><h3>{group.relative?t(group.relative):group.date==='unknown'?t('Date unavailable'):group.date}</h3>{group.rows.map(row=><button className="history-entry" disabled={disabled} key={row.id} aria-pressed={selectedId===row.id} onClick={()=>onSelect(row)}><span>{row.user_text.slice(0,120)}</span><time>{time(row.created_at)}</time></button>)}</section>)}
  {cursor?<button disabled={loading} onClick={()=>setPageBefore(cursor)}>{t('Load earlier conversations')}</button>:null}
 </aside>;
}
