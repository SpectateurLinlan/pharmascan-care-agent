import {useEffect, useState} from 'react';
import {api, type CaregiverContact, type CaregiverDetails} from '../api/client';
import {useLanguage} from '../language';
import {BottomSheet} from './BottomSheet';
import {Card, ErrorNotice} from './primitives';

type Draft={id:string;name:string;relationship:string;contact_type:'email'|'phone';contact_value:string;consent:boolean;editing:boolean};
export function CaregiversScreen({newId=()=>crypto.randomUUID()}: {newId?:()=>string}) {
  const {t}=useLanguage();
  const [rows,setRows]=useState<CaregiverContact[]>([]),[loading,setLoading]=useState(true),[busy,setBusy]=useState(false);
  const [error,setError]=useState<unknown>(null),[draft,setDraft]=useState<Draft|null>(null),[remove,setRemove]=useState<CaregiverContact|null>(null);
  async function reload(){setLoading(true);try{setRows(await api.caregivers());setError(null);}catch(caught){setError(caught);}finally{setLoading(false);}}
  useEffect(()=>{let active=true;void api.caregivers().then(value=>{if(active){setRows(value);setLoading(false);}}).catch(caught=>{if(active){setError(caught);setLoading(false);}});return()=>{active=false;};},[]);
  async function save(){
    if(!draft?.consent||busy)return;
    setBusy(true);setError(null);
    const details:CaregiverDetails={name:draft.name.trim(),relationship:draft.relationship.trim()||null,contact_type:draft.contact_type,contact_value:draft.contact_value.trim(),storage_consent:true};
    try{
      const saved=draft.editing?await api.updateCaregiver(draft.id,details):await api.createCaregiver({...details,id:draft.id});
      setRows(previous=>[...previous.filter(row=>row.id!==saved.id),saved]);setDraft(null);
    }catch(caught){setError(caught);}finally{setBusy(false);}
  }
  async function deleteContact(){if(!remove||busy)return;setBusy(true);setError(null);try{await api.deleteCaregiver(remove.id);setRows(previous=>previous.filter(row=>row.id!==remove.id));setRemove(null);}catch(caught){setError(caught);}finally{setBusy(false);}}
  return <><Card title="Caregiver contacts">
    <p>{t('Contacts are for your own reference. Saving one does not message the person or share your records.')}</p>
    <p className="notice">{t('Contacts are stored now. Verification and notifications are not switched on yet.')}</p>
    <button className="primary" disabled={loading||Boolean(error)||busy} onClick={()=>setDraft({id:newId(),name:'',relationship:'',contact_type:'email',contact_value:'',consent:false,editing:false})}>{t('Add caregiver contact')}</button>
    {loading?<p role="status">{t('Loading contacts…')}</p>:null}
    {!loading&&!error&&!rows.length?<p>{t('No caregiver contacts saved yet.')}</p>:null}
    {error&&!draft&&!remove?<><ErrorNotice error={error}/><button onClick={()=>void reload()}>{t('Retry loading contacts')}</button></>:null}
    <ul className="caregiver-list">{rows.map(row=><li key={row.id}><h3>{row.name}</h3>{row.relationship?<p>{row.relationship}</p>:null}<p>{row.contact_value}</p>
      <p className="notice">{t('Not verified')} · {t('Notifications off')} · {t('No record access')}</p>
      <div className="actions"><button onClick={()=>{setError(null);setDraft({id:row.id,name:row.name,relationship:row.relationship??'',contact_type:row.contact_type,contact_value:row.contact_value,consent:false,editing:true});}}>{t('Edit contact')}</button><button onClick={()=>{setError(null);setRemove(row);}}>{t('Delete contact')}</button></div>
    </li>)}</ul>
  </Card>
  {draft?<BottomSheet title={t(draft.editing?'Edit contact':'Add caregiver contact')} busy={busy} onCancel={()=>{setDraft(null);setError(null);}}>
    <form onSubmit={event=>{event.preventDefault();void save();}}>
      <label className="field">{t('Contact name')}<input required maxLength={80} autoComplete="off" value={draft.name} onChange={event=>setDraft({...draft,name:event.target.value})}/></label>
      <label className="field">{t('Relationship (optional)')}<input maxLength={80} autoComplete="off" value={draft.relationship} onChange={event=>setDraft({...draft,relationship:event.target.value})}/></label>
      <label className="field">{t('Contact method')}<select value={draft.contact_type} onChange={event=>setDraft({...draft,contact_type:event.target.value==='phone'?'phone':'email',contact_value:''})}><option value="email">{t('Email')}</option><option value="phone">{t('Phone')}</option></select></label>
      <label className="field">{t(draft.contact_type==='email'?'Email address':'Phone with country code')}<input required type={draft.contact_type==='email'?'email':'tel'} maxLength={254} autoComplete="off" value={draft.contact_value} onChange={event=>setDraft({...draft,contact_value:event.target.value})}/></label>
      <label className="consent"><input type="checkbox" checked={draft.consent} onChange={event=>setDraft({...draft,consent:event.target.checked})}/>{t('I have this person’s permission to save their details. This only stores the contact — it does not share my records.')}</label>
      {error?<ErrorNotice error={error}/>:null}
      <div className="actions"><button type="button" disabled={busy} onClick={()=>{setDraft(null);setError(null);}}>{t('Cancel')}</button><button className="primary" type="submit" disabled={busy||!draft.consent||!draft.name.trim()||!draft.contact_value.trim()}>{t('Save contact')}</button></div>
    </form>
  </BottomSheet>:null}
  {remove?<BottomSheet title={t('Delete caregiver contact?')} busy={busy} onCancel={()=>{setRemove(null);setError(null);}}><p>{remove.name}</p><p>{t('This removes the saved contact. Your medication records will not change.')}</p>{error?<ErrorNotice error={error}/>:null}<div className="actions"><button disabled={busy} onClick={()=>{setRemove(null);setError(null);}}>{t('Cancel')}</button><button className="primary" disabled={busy} onClick={()=>void deleteContact()}>{t('Confirm deletion')}</button></div></BottomSheet>:null}
  </>;
}
