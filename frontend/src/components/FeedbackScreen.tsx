import {useState} from 'react';
import {api} from '../api/client';
import {useLanguage} from '../language';
import {Card,ErrorNotice} from './primitives';
export function FeedbackScreen(){const {t}=useLanguage();const [category,setCategory]=useState<'issue'|'suggestion'>('issue'),[message,setMessage]=useState(''),[busy,setBusy]=useState(false),[saved,setSaved]=useState(false),[error,setError]=useState<unknown>(null),[id]=useState(()=>crypto.randomUUID());
 async function submit(){setBusy(true);setError(null);try{await api.feedback({id,category,message});setSaved(true);}catch(error){setError(error);}finally{setBusy(false);}}
 return <Card title="Feedback"><p>{t('Share an app issue or suggestion. Do not include medical records, passwords or verification codes. This is not an emergency channel.')}</p>
 {saved?<p role="status">{t('Feedback saved for review. No email or medical notification was sent.')}</p>:<><label className="field">{t('Category')}<select value={category} onChange={event=>setCategory(event.target.value==='suggestion'?'suggestion':'issue')}><option value="issue">{t('App issue')}</option><option value="suggestion">{t('Suggestion')}</option></select></label>
 <label className="field">{t('Your feedback')}<textarea value={message} minLength={5} maxLength={2000} onChange={event=>setMessage(event.target.value)}/></label><button className="primary" disabled={busy||message.trim().length<5} onClick={()=>void submit()}>{t('Send feedback')}</button></>}{error?<ErrorNotice error={error}/>:null}</Card>;
}
