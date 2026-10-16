import {useEffect,useState,useRef} from 'react';
import {api} from '../api/client';
import type {DoseBasis,DoseDisplay} from '../api/dose';
import {useLanguage} from '../language';
import {ErrorNotice} from './primitives';

export const emptyDoseBasis:DoseBasis={strength_text:'',form:'unknown',formulation:'unknown',single_ingredient:null,instructions_text:'',patient_checked:false};

/** Source evidence and server-calculated display only. Never derives a pill count. */
export function DoseDetails({basis,onChange,amount,unit,id='dose-basis'}:{basis:DoseBasis;onChange:(value:DoseBasis)=>void;amount:string;unit:string;id?:string}){
 const mounted=useRef(true);const current=useRef({basis,amount,unit});current.current={basis,amount,unit};
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;};},[]);
 const {t}=useLanguage();const [result,setResult]=useState<DoseDisplay|null>(null),[error,setError]=useState<unknown>(null),[busy,setBusy]=useState(false);
 useEffect(()=>{setResult(null);setError(null);},[basis,amount,unit]);
 function update(changes:Partial<DoseBasis>){onChange({...basis,...changes,patient_checked:false});}
 return <details className="dose-evidence"><summary>{t('Product strength and original instructions')}</summary>
 <p className="notice">{t('Strength describes the product. Enter the number to take separately from your instructions.')}</p>
 <label className="field" htmlFor={`${id}-strength`}>{t('Strength per tablet or capsule')}<input id={`${id}-strength`} maxLength={100} placeholder="500 mg" value={basis.strength_text} onChange={event=>update({strength_text:event.target.value})}/></label>
 <div className="grid-2"><label className="field">{t('Dosage form')}<select aria-label={t('Dosage form')} value={basis.form} onChange={event=>update({form:event.target.value as DoseBasis['form']})}>{(['unknown','tablet','capsule','liquid','other'] as const).map(value=><option key={value} value={value}>{t(value==='unknown'?'Not specified':value)}</option>)}</select></label>
 <label className="field">{t('Formulation')}<select aria-label={t('Formulation')} value={basis.formulation} onChange={event=>update({formulation:event.target.value as DoseBasis['formulation']})}>{(['unknown','standard','modified_release','enteric'] as const).map(value=><option key={value} value={value}>{t(value==='unknown'?'Not specified':value==='standard'?'Standard release':value==='modified_release'?'Modified release':'Enteric coated')}</option>)}</select></label></div>
 <label className="field">{t('Ingredients documented')}<select aria-label={t('Ingredient scope')} value={basis.single_ingredient===true?'single':basis.single_ingredient===false?'multiple':'unknown'} onChange={event=>update({single_ingredient:event.target.value==='single'?true:event.target.value==='multiple'?false:null})}><option value="unknown">{t('Not specified')}</option><option value="single">{t('One active ingredient')}</option><option value="multiple">{t('More than one active ingredient')}</option></select></label>
 <label className="field">{t('Original dose instructions')}<textarea maxLength={1000} value={basis.instructions_text} onChange={event=>update({instructions_text:event.target.value})}/></label>
 <label className="consent"><input type="checkbox" checked={basis.patient_checked} onChange={event=>onChange({...basis,patient_checked:event.target.checked})}/>{t('I checked the strength, form and count against my original instructions.')}</label>
 <button disabled={busy||!basis.patient_checked||!amount||!Number.isFinite(Number(amount))||Number(amount)<=0} onClick={async()=>{setBusy(true);setError(null);try{const value=await api.doseDisplay(basis,Number(amount),unit);if(mounted.current&&current.current.basis===basis&&current.current.amount===amount&&current.current.unit===unit)setResult(value);}catch(caught){if(mounted.current&&current.current.basis===basis&&current.current.amount===amount)setError(caught);}finally{if(mounted.current)setBusy(false);}}}>{t('Show total from these details')}</button>
 {busy?<p role="status">{t('Checking the entered details…')}</p>:null}{error?<ErrorNotice error={error}/>:null}{result?<p role={result.status==='conflict'?'alert':'status'}>{result.status==='calculated'?`${t('Total per dose')}: ${result.total_amount} ${result.total_unit}`:t('Total not calculated')}. {t(result.reason)}</p>:null}
 </details>;
}
