import {useEffect,useRef,useState} from 'react';
import {api,type ConversationEntry} from '../api/client';
import {useLanguage} from '../language';
import {BottomSheet} from './BottomSheet';
import {ErrorNotice} from './primitives';

/**
 * Saved conversation history.
 *
 * The switch enables saving for *future* turns. It does not backfill messages
 * from before it was turned on, so the label, the explanation and the state
 * line all say "from now on" rather than implying the current chat was stored.
 * The retention window, the consent behaviour and the persistence calls are
 * unchanged.
 */
export function ConversationHistory({revision,onCleared,blocked=false}:{revision:number;onCleared:()=>void;blocked?:boolean}){
 const {t,language,preferences,updatePreferences,preferenceError}=useLanguage();const [savingPreference,setSavingPreference]=useState(false);const [saveState,setSaveState]=useState<'idle'|'saved'|'failed'>('idle');const [open,setOpen]=useState(false),[rows,setRows]=useState<ConversationEntry[]>([]),[cursor,setCursor]=useState<string|null>(null),[error,setError]=useState<unknown>(null),[loading,setLoading]=useState(false),[confirm,setConfirm]=useState(false);
 // The provider reports a failed preference save through context state rather
 // than by rejecting, so the latest value is read after the update settles.
 const preferenceErrorRef=useRef(preferenceError);preferenceErrorRef.current=preferenceError;
 useEffect(()=>{if(!open)return;let live=true;setLoading(true);setError(null);void api.conversationHistory().then(page=>{if(live){setRows(page.entries);setCursor(page.next_before);}}).catch(caught=>{if(live)setError(caught);}).finally(()=>{if(live)setLoading(false);});return()=>{live=false;};},[open,revision]);
 async function more(){if(!cursor)return;setLoading(true);setError(null);try{const page=await api.conversationHistory(cursor);setRows(previous=>[...previous,...page.entries.filter(row=>!previous.some(old=>old.id===row.id))]);setCursor(page.next_before);}catch(caught){setError(caught);}finally{setLoading(false);}}
 const enabled=preferences.conversation_history_enabled??false;
 async function saveHistoryPreference(next:boolean){
  setSavingPreference(true);setSaveState('idle');
  try{
   await updatePreferences({conversation_history_enabled:next});
   // Let the provider's own error state land before reading it.
   await new Promise(resolve=>setTimeout(resolve,0));
   setSaveState(preferenceErrorRef.current?'failed':'saved');
  }catch{setSaveState('failed');}finally{setSavingPreference(false);}
 }
 return <details className="conversation-history" onToggle={event=>setOpen(event.currentTarget.open)}><summary>{t('Saved conversations')}</summary>
 <p>{t('Optional history shows up to 200 conversations from the last 30 days. This is a viewing window, not scheduled deletion. Use Clear saved conversations to remove stored chat text. Medication records are separate.')}</p>
 <label className="consent"><input type="checkbox" disabled={savingPreference} checked={enabled} onChange={event=>void saveHistoryPreference(event.target.checked)}/>{t('Save new conversations on this account')}</label>
 <p className="history-state">{t('Saving starts from now on. Messages sent before you turn this on are not added.')}</p>
 {savingPreference?<p role="status">{t('Saving preference...')}</p>:null}
 {saveState==='saved'?<p className="history-state" role="status">{enabled?t('Saving is on. New conversations will be stored on this account.'):t('Saving is off. New conversations will not be stored.')}</p>:null}
 {saveState==='failed'?<div className="history-retry" role="alert"><p>{t('Could not confirm the saving setting. Reload to check its current status, then try again.')}</p><button disabled={savingPreference} onClick={()=>void saveHistoryPreference(!enabled)}>{t('Try again')}</button></div>:null}
 {!saveState&&preferenceError?<p role="alert">{t(preferenceError)}</p>:null}{error?<ErrorNotice error={error}/>:null}{loading?<p role="status">{t('Loading conversations…')}</p>:null}{!loading&&!error&&!rows.length?<p>{t('No saved conversations yet.')}</p>:null}
 {rows.map(row=><article className="history-message" key={row.id}><time>{new Date(row.created_at).toLocaleString(language==='zh'?'zh-CN':'en-SG',{timeZone:preferences.timezone})}</time><p className="user-message">{row.user_text}</p><p>{row.assistant_text}</p></article>)}
 {cursor?<button disabled={loading} onClick={()=>void more()}>{t('Load earlier conversations')}</button>:null}<button disabled={loading||blocked} onClick={()=>setConfirm(true)}>{t('Clear saved conversations')}</button>
 {confirm?<BottomSheet title={t('Clear saved conversations?')} busy={loading} onCancel={()=>setConfirm(false)}><p>{t('This removes saved messages and recent chat text. Your medication plans, reports and follow-ups stay in their own records.')}</p><button className="primary" disabled={loading} onClick={async()=>{setLoading(true);setError(null);try{await api.clearConversationHistory();setRows([]);setCursor(null);setConfirm(false);onCleared();}catch(caught){setError(caught);}finally{setLoading(false);}}}>{t('Confirm clear')}</button><button disabled={loading} onClick={()=>setConfirm(false)}>{t('Cancel')}</button></BottomSheet>:null}
 </details>;
}
