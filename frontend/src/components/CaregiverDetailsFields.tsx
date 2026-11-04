import {useLanguage} from '../language';

export interface CaregiverEditorDraft {name:string;relationship:string;contact_type:'email'|'phone';contact_value:string;consent:boolean}
/** Shared native fields only; each caller owns persistence and independent review. */
export function CaregiverDetailsFields({draft,onChange,busy=false}:{draft:CaregiverEditorDraft;onChange:(value:CaregiverEditorDraft)=>void;busy?:boolean}){
 const {t}=useLanguage();
 return <>
  <label className="field">{t('Contact name')}<input required maxLength={80} autoComplete="off" disabled={busy} value={draft.name} onChange={event=>onChange({...draft,name:event.target.value})}/></label>
  <label className="field">{t('Relationship (optional)')}<input maxLength={80} autoComplete="off" disabled={busy} value={draft.relationship} onChange={event=>onChange({...draft,relationship:event.target.value})}/></label>
  <label className="field">{t('Contact method')}<select disabled={busy} value={draft.contact_type} onChange={event=>onChange({...draft,contact_type:event.target.value==='phone'?'phone':'email',contact_value:''})}><option value="email">{t('Email')}</option><option value="phone">{t('Phone')}</option></select></label>
  <label className="field">{t(draft.contact_type==='email'?'Email address':'Phone with country code')}<input required type={draft.contact_type==='email'?'email':'tel'} maxLength={254} autoComplete="off" disabled={busy} value={draft.contact_value} onChange={event=>onChange({...draft,contact_value:event.target.value})}/></label>
  <label className="consent"><input type="checkbox" disabled={busy} checked={draft.consent} onChange={event=>onChange({...draft,consent:event.target.checked})}/>{t('I have this person’s permission to save their details. This only stores the contact — it does not share my records.')}</label>
  <p className="notice">{t('Your confirmation is not independent verification.')}</p>
 </>;
}
