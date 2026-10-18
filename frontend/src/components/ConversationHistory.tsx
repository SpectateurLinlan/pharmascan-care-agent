import {useRef,useState} from 'react';
import {api} from '../api/client';
import {useLanguage} from '../language';
import {BottomSheet} from './BottomSheet';
import {ErrorNotice} from './primitives';

/**
 * Saved conversation history.
 *
 * The switch enables saving for *future* turns. It does not backfill messages
 * from before it was turned on, so the label, the explanation and the state
 * line all say "from now on" rather than implying the current chat was stored.
 * Durable threads and legacy exchanges have different retention rules.
 */
export function ConversationHistory({onCleared,blocked=false}:{revision?:number;onCleared:()=>void;blocked?:boolean}){
 const {t,preferences,updatePreferences,preferenceError}=useLanguage();const [savingPreference,setSavingPreference]=useState(false);const [saveState,setSaveState]=useState<'idle'|'saved'|'failed'>('idle');const [error,setError]=useState<unknown>(null),[loading,setLoading]=useState(false),[confirm,setConfirm]=useState(false),[info,setInfo]=useState(false);
 // The provider reports a failed preference save through context state rather
 // than by rejecting, so the latest value is read after the update settles.
 const preferenceErrorRef=useRef(preferenceError);preferenceErrorRef.current=preferenceError;
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
 return <section className="conversation-history">
 <div className="history-controls"><label className="consent"><input type="checkbox" disabled={savingPreference} checked={enabled} onChange={event=>void saveHistoryPreference(event.target.checked)}/><span>{t('Save new conversations')}<small>{t('Only new messages are saved when this is enabled.')}</small></span></label><button className="icon-button" aria-label={t('About saved conversations')} onClick={()=>setInfo(true)}>?</button></div>
 {info?<BottomSheet title={t('About saved conversations')} onCancel={()=>setInfo(false)}><p>{t('Saved conversations can be reopened and continued. Older exchanges without a conversation identity remain read-only within the existing 30-day, 200-exchange window. Clearing removes saved and recent chat text, not medication or health records.')}</p><p>{t('Saving starts from now on. Messages sent before you turn this on are not added.')}</p><button onClick={()=>setInfo(false)}>{t('Close')}</button></BottomSheet>:null}
 {savingPreference?<p role="status">{t('Saving preference...')}</p>:null}
 {saveState==='saved'?<p className="history-state" role="status">{enabled?t('Saved history is on. New messages will be added to it.'):t('Saved history is off. New messages will not be added to it.')}</p>:null}
 {saveState==='failed'?<div className="history-retry" role="alert"><p>{t('Could not confirm the saving setting. Reload to check its current status, then try again.')}</p><button disabled={savingPreference} onClick={()=>void saveHistoryPreference(!enabled)}>{t('Try again')}</button></div>:null}
 {error&&!confirm?<ErrorNotice error={error}/>:null}
 <button disabled={loading||blocked} onClick={()=>setConfirm(true)}>{t('Clear saved conversations')}</button>
 {confirm?<BottomSheet title={t('Clear saved conversations?')} busy={loading} onCancel={()=>setConfirm(false)}><p>{t('This removes saved messages and recent chat text. Your medication plans, reports and follow-ups stay in their own records.')}</p>{error?<p role="alert">{t('Could not confirm clearing. Retry or cancel.')}</p>:null}<button className="primary" disabled={loading} onClick={async()=>{setLoading(true);setError(null);try{await api.clearConversationHistory();setConfirm(false);onCleared();}catch(caught){setError(caught);}finally{setLoading(false);}}}>{t('Confirm clear')}</button><button disabled={loading} onClick={()=>setConfirm(false)}>{t('Cancel')}</button></BottomSheet>:null}
 </section>;
}
