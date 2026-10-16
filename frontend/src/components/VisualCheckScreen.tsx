import { useLanguage } from '../language';
import {useEffect,useRef,useState} from 'react';
import {api,type VisualCheckResult,type RecognitionEvidence,type ImageRoute} from '../api/client';
import {ErrorNotice} from './primitives';
export function VisualCheckScreen({regimenId,onBack,onAddSource,showBack=true,showResult=true,onResult,initialFile=null}:{regimenId:string|null;onBack:()=>void;onAddSource?:()=>void;showBack?:boolean;showResult?:boolean;onResult?:()=>void;initialFile?:File|null}) {
 const {t}=useLanguage();
 const mounted=useRef(true);useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;};},[]);
 const [file,setFile]=useState<File|null>(initialFile),[preview,setPreview]=useState(''),[consent,setConsent]=useState(false),[busy,setBusy]=useState(false),[result,setResult]=useState<VisualCheckResult|null>(null),[error,setError]=useState<unknown>(null);
 const [intent,setIntent]=useState<'check_dose'|'identify'>(regimenId?'check_dose':'identify'),[personal,setPersonal]=useState<RecognitionEvidence|null>(null);
 const [route,setRoute]=useState<ImageRoute|null>(null);
 async function routePhoto(){if(!file||!consent)return;setBusy(true);setError(null);setRoute(null);try{setRoute(await api.checkInput(file));}catch(caught){setError(caught);}finally{setBusy(false);}}
 useEffect(()=>{if(!file){setPreview('');return;} const url=URL.createObjectURL(file);setPreview(url);return()=>URL.revokeObjectURL(url);},[file]);
 async function check(){if(!file||!consent)return;setBusy(true);setError(null);setResult(null);setPersonal(null);try{
  if(intent==='check_dose'){const response=await api.checkPersonalDose(file,regimenId);if(!mounted.current)return;setPersonal(response);}
  else {const response=await api.visualCheck(file,null);if(!mounted.current)return;setResult(response);}
  onResult?.();
 }catch(e){if(mounted.current)setError(e);}finally{if(mounted.current)setBusy(false);}}
 const hasResult=showResult&&Boolean(result||personal);
 return <section className="card">{showBack?<button onClick={onBack}>{t('Back')}</button>:null}<h1>{t(hasResult?'Photo check result':'Compare a pill photo')}</h1><p className="notice">{t('We compare your photo with the references you have saved. A photo cannot tell you whether a medicine is safe to take.')}</p>
 <div hidden={hasResult}><div className="actions"><button disabled={busy} aria-pressed={intent==='check_dose'} onClick={()=>{setIntent('check_dose');setResult(null);setPersonal(null);}}>{t('Check this dose')}</button><button disabled={busy} aria-pressed={intent==='identify'} onClick={()=>{setIntent('identify');setResult(null);setPersonal(null);}}>{t('Identify a pill')}</button>{onAddSource?<button onClick={onAddSource}>{t('Add medication information')}</button>:null}</div><p>{t(intent==='check_dose'?'Compare with your personal pill references and current plan.':'Look for catalogue candidates for an unknown pill.')}</p>
 <label>{t('Take or choose a photo')}<input type="file" disabled={busy} accept="image/png,image/jpeg" capture="environment" onChange={e=>{setFile(e.target.files?.[0]??null);setResult(null);setPersonal(null);setRoute(null);}}/></label>
 {preview?<img className="photo-preview" src={preview} alt={t('Selected image preview')}/>:null}
 <label className="consent"><input type="checkbox" checked={consent} onChange={e=>setConsent(e.target.checked)}/>{t('This is a synthetic demo image. I agree to send it for visual evidence.')}</label>
 <button className="primary" disabled={!file||!consent||busy} onClick={()=>void check()}>{t(busy?'Checking photo...':'Check photo')}</button>
 <button disabled={!file||!consent||busy} onClick={()=>void routePhoto()}>{t('Not sure which photo workflow to use?')}</button>
 {route?<div role="status"><p>{t(route.suggested_workflow==='source_review'?'This looks like printed information. Read and review the source.':route.suggested_workflow==='pill_evidence'?'This may be a loose pill photo. Choose a check above.':'Please choose the photo type or provide the original label. Blister matching is not verified.')}</p>{route.suggested_workflow==='source_review'&&onAddSource?<button onClick={onAddSource}>{t('Add medication information')}</button>:null}</div>:null}
 </div>{hasResult&&onAddSource?<button onClick={onAddSource}>{t('Add medication information')}</button>:null}
 {error?<ErrorNotice error={error}/>:null}
 {showResult&&personal?<div aria-live="polite"><h2>{t(personal.decision==='match'?'Visual reference evidence found':personal.decision==='conflict'?'Photo and current plan need clarification':personal.decision==='missing_reference'?'Add a personal reference first':personal.decision==='unavailable'?'Photo comparison temporarily unavailable':'Photo needs another look')}</h2><p>{t(personal.reason)}</p>{personal.outcome?.closest?<p>{t('Closest personal reference')}: {personal.outcome.closest.name}</p>:null}<p>{t('A photo cannot prove ingestion. Any intake report requires separate confirmation.')}</p><p>{t('Compare the original label and your reviewed instructions before making a medication decision.')}</p></div>:null}
 {showResult&&result?<div aria-live="polite"><h2>{t(result.decision==='ambiguous'?'Photo needs another look':'Medicine remains unverified')}</h2><p>{result.selected_medication ? `${t('Selected schedule')}: ${result.selected_medication}`:t('No medication selected.')}</p><p>{t(result.reason)}</p>
 <p>{t('Catalogue candidates are visual evidence only. Similarity is not identification confidence or safe-to-take approval.')}</p>
 <ul>{result.candidates.map(item=><li key={item.external_catalogue_id}>{item.display_name??t('Unnamed candidate')} {item.strength??''} ({t('US catalogue')})</li>)}</ul>
 <p>{t(result.next_action)}</p><p>{t('A photo cannot prove ingestion. Any intake report requires separate confirmation.')}</p></div>:null}</section>;
}
