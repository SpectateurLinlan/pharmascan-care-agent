import {useState} from 'react';
import {api} from '../api/client';
import {useLanguage} from '../language';
import {AutoDismissNotice,Card,ErrorNotice} from './primitives';
import {Screen} from '../ui/primitives';
export function FeedbackScreen(){const {t}=useLanguage();const [category,setCategory]=useState<'issue'|'suggestion'>('issue'),[message,setMessage]=useState(''),[busy,setBusy]=useState(false),[saved,setSaved]=useState(false),[error,setError]=useState<unknown>(null),[id]=useState(()=>crypto.randomUUID());
 async function submit(){if(busy||message.trim().length<5)return;setBusy(true);setError(null);try{await api.feedback({id,category,message:message.trim()});setSaved(true);}catch(error){setError(error);}finally{setBusy(false);}}
 return <Screen title="Feedback & Suggestions" className="feedback-screen"><Card><p>{t('Tell us about an app issue or an improvement. Do not include passwords, verification codes or unnecessary sensitive medical information.')}</p>
 {saved?<><p role="status">{t('Your feedback was saved to your account feedback record. This does not mean it was emailed or reviewed.')}</p><AutoDismissNotice>{t('Feedback saved.')}</AutoDismissNotice></>:<form onSubmit={event=>{event.preventDefault();void submit();}}><label className="field">{t('Category')}<select value={category} onChange={event=>setCategory(event.target.value==='suggestion'?'suggestion':'issue')}><option value="issue">{t('App issue')}</option><option value="suggestion">{t('Suggestion')}</option></select></label>
 <label className="field">{t('Description')}<textarea required value={message} minLength={5} maxLength={2000} onChange={event=>setMessage(event.target.value)}/></label><button className="primary" type="submit" disabled={busy||message.trim().length<5}>{busy?t('Submitting...'):t('Send feedback')}</button></form>}{error?<ErrorNotice error={error}/>:null}</Card></Screen>;
}
