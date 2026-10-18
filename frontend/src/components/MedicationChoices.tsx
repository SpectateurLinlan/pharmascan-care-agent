import {useEffect,useState} from 'react';
import type {MedicationChoice,MedicationSelection} from '../api/client';
import {useLanguage} from '../language';

export function MedicationChoices({choice,disabled,onChoose}:{choice:MedicationChoice;disabled:boolean;onChoose:(selection:MedicationSelection,label:string)=>void}){
 const {t}=useLanguage();const [now,setNow]=useState(Date.now);
 useEffect(()=>{const timer=window.setInterval(()=>setNow(Date.now()),1000);return()=>window.clearInterval(timer);},[]);
 const expired=Date.parse(choice.expires_at)<=now;
 return <section className="medication-choices" aria-label={t('Choose a medicine')}>
  {choice.options.map(option=><button type="button" key={option.medication_id} disabled={disabled||expired} onClick={()=>onChoose({choice_id:choice.id,medication_id:option.medication_id},option.label)}>{option.label}</button>)}
  {expired?<p role="status">{t('These choices expired. Ask your question again to refresh them.')}</p>:null}
 </section>;
}
