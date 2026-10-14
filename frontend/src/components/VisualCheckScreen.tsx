import { useLanguage } from '../language';
import {useEffect,useState} from 'react';
import {api,type VisualCheckResult,type RecognitionEvidence} from '../api/client';
import {ErrorNotice} from './primitives';
export function VisualCheckScreen({regimenId,onBack,onAddSource}:{regimenId:string|null;onBack:()=>void;onAddSource?:()=>void}) {
 const {t}=useLanguage();
 const [file,setFile]=useState<File|null>(null),[preview,setPreview]=useState(''),[consent,setConsent]=useState(false),[busy,setBusy]=useState(false),[result,setResult]=useState<VisualCheckResult|null>(null),[error,setError]=useState<unknown>(null);
 const [intent,setIntent]=useState<'check_dose'|'identify'>(regimenId?'check_dose':'identify'),[personal,setPersonal]=useState<RecognitionEvidence|null>(null);
 useEffect(()=>{if(!file){setPreview('');return;} const url=URL.createObjectURL(file);setPreview(url);return()=>URL.revokeObjectURL(url);},[file]);
 async function check(){if(!file||!consent)return;setBusy(true);setError(null);setResult(null);setPersonal(null);try{if(intent==='check_dose')setPersonal(await api.checkPersonalDose(file,regimenId));else setResult(await api.visualCheck(file,null));}catch(e){setError(e);}finally{setBusy(false);}}
 return <section className="card"><button onClick={onBack}>{t('Back to Today')}</button><h1>{t('Check my medicine')}</h1>
 <div className="actions"><button aria-pressed={intent==='check_dose'} onClick={()=>{setIntent('check_dose');setResult(null);setPersonal(null);}}>{t('Check this dose')}</button><button aria-pressed={intent==='identify'} onClick={()=>{setIntent('identify');setResult(null);setPersonal(null);}}>{t('Identify a pill')}</button>{onAddSource?<button onClick={onAddSource}>{t('Add medication information')}</button>:null}</div><p>{t(intent==='check_dose'?'Compare with your personal pill references and current plan.':'Look for catalogue candidates for an unknown pill.')}</p>
 <label>{t('Take or choose a photo')}<input type="file" accept="image/png,image/jpeg" capture="environment" onChange={e=>{setFile(e.target.files?.[0]??null);setResult(null);setPersonal(null);}}/></label>
 {preview?<img className="photo-preview" src={preview} alt={t('Selected image preview')}/>:null}
 <label className="consent"><input type="checkbox" checked={consent} onChange={e=>setConsent(e.target.checked)}/>{t('This is a synthetic demo image. I agree to send it for visual evidence.')}</label>
 <button className="primary" disabled={!file||!consent||busy} onClick={()=>void check()}>{t(busy?'Checking photo...':'Check photo')}</button>
 {error?<ErrorNotice error={error}/>:null}
 {personal?<div aria-live="polite"><h2>{t(personal.decision==='match'?'Visual reference evidence found':personal.decision==='conflict'?'Photo and current plan need clarification':personal.decision==='missing_reference'?'Add a personal reference first':personal.decision==='unavailable'?'Photo comparison temporarily unavailable':'Photo needs another look')}</h2><p>{t(personal.reason)}</p>{personal.outcome?.closest?<p>{t('Closest personal reference')}: {personal.outcome.closest.name}</p>:null}<p>{t('A photo cannot prove ingestion. Any intake report requires separate confirmation.')}</p><p>{t('Compare the original label and your reviewed instructions before making a medication decision.')}</p></div>:null}
 {result?<div aria-live="polite"><h2>{t(result.decision==='ambiguous'?'Photo needs another look':'Medicine remains unverified')}</h2><p>{result.selected_medication ? `${t('Selected schedule')}: ${result.selected_medication}`:t('No medication selected.')}</p><p>{t(result.reason)}</p>
 <p>{t('Catalogue candidates are visual evidence only. Similarity is not identification confidence or safe-to-take approval.')}</p>
 <ul>{result.candidates.map(item=><li key={item.external_catalogue_id}>{item.display_name??t('Unnamed candidate')} {item.strength??''} ({t('US catalogue')})</li>)}</ul>
 <p>{t(result.next_action)}</p><p>{t('A photo cannot prove ingestion. Any intake report requires separate confirmation.')}</p></div>:null}</section>;
}
