import {useRef,useState} from 'react';
import {api} from '../api/client';
import {useLanguage} from '../language';
import {BottomSheet} from './BottomSheet';
import {AutoDismissNotice,ErrorNotice} from './primitives';
import {Icon} from './Icon';

/**
 * Saved conversation history.
 *
 * The switch enables saving for *future* turns. It does not backfill messages
 * from before it was turned on, so the label, the explanation and the state
 * line all say "from now on" rather than implying the current chat was stored.
 * Durable threads and legacy exchanges have different retention rules.
 */
export function ConversationHistory({onCleared,blocked=false}:{revision?:number;onCleared:()=>void;blocked?:boolean}){
 const {t,preferences,updatePreferences,preferenceError}=useLanguage();const [savingPreference,setSavingPreference]=useState(false);const [saveState,setSaveState]=useState<'idle'|'saved'|'failed'>('idle');const [error,setError]=useState<unknown>(null),[loading,setLoading]=useState(false),[confirm,setConfirm]=useState(false),[info,setInfo]=useState(false),[cleared,setCleared]=useState(false);
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
 return <section className="conversation-history">{cleared?<AutoDismissNotice>{t('Saved conversations cleared.')}</AutoDismissNotice>:null}
 <div className="history-controls">
  <Icon name="message"/>
  <div className="history-setting-copy"><strong>{t('Save new conversations')}</strong><small id="conversation-saving-description">{t('Only new messages are saved when this is enabled.')}</small></div>
  <button type="button" className="history-switch" role="switch" aria-label={t('Save new conversations')} aria-describedby="conversation-saving-description" aria-checked={enabled} aria-busy={savingPreference} disabled={savingPreference} onClick={()=>void saveHistoryPreference(!enabled)}><span/></button>
 </div>
 {info?<BottomSheet title={t('AI assistant use information')} onCancel={()=>setInfo(false)}><p>{t('The assistant keeps up to six recent exchanges for current context, separately from optional saved history.')}</p><p>{t('Saved conversations can be reopened and continued. Older exchanges without a conversation identity remain read-only within the existing 30-day, 200-exchange window. Clearing removes saved and recent chat text, not medication or health records.')}</p><p>{t('Saving starts from now on. Messages sent before you turn this on are not added.')}</p><button onClick={()=>setInfo(false)}>{t('Close')}</button></BottomSheet>:null}
 {savingPreference?<p role="status">{t('Saving preference...')}</p>:null}
 {saveState==='saved'?<p className="history-state" role="status">{enabled?t('Saved history is on. New messages will be added to it.'):t('Saved history is off. New messages will not be added to it.')}</p>:null}
 {saveState==='failed'?<div className="history-retry" role="alert"><p>{t('Could not confirm the saving setting. Reload to check its current status, then try again.')}</p><button disabled={savingPreference} onClick={()=>void saveHistoryPreference(!enabled)}>{t('Try again')}</button></div>:null}
 {error&&!confirm?<ErrorNotice error={error}/>:null}
 <button type="button" className="history-clear" disabled={loading||blocked} onClick={()=>setConfirm(true)}>{t('Clear saved conversations')}</button>
 <button type="button" className="history-info-row" aria-haspopup="dialog" onClick={()=>setInfo(true)}><span className="history-info-row__icon"><Icon name="info"/></span><span className="history-info-row__text"><strong>{t('AI assistant use information')}</strong><small>{t('About recent context, saved history and voice processing.')}</small></span><Icon name="chevron-right"/></button>
 {confirm?<BottomSheet title={t('Clear saved conversations?')} busy={loading} onCancel={()=>setConfirm(false)}><p>{t('This removes the saved conversation history available through MediThread. It does not delete medication plans, reports or follow-ups, and does not request deletion from external AI providers.')}</p>{error?<p role="alert">{t('Could not confirm clearing. Retry or cancel.')}</p>:null}<button className="primary" disabled={loading} onClick={async()=>{setLoading(true);setError(null);try{await api.clearConversationHistory();setConfirm(false);setCleared(true);onCleared();}catch(caught){setError(caught);}finally{setLoading(false);}}}>{loading?t('Clearing...'):t('Confirm clear')}</button><button disabled={loading} onClick={()=>setConfirm(false)}>{t('Cancel')}</button></BottomSheet>:null}
 </section>;
}
