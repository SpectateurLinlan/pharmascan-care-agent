import {api,type DoseHistoryResponse,type MedicationSummary,type RegimenHistoryItem} from '../api/client';
import {useEffect,useState} from 'react';
import {useLanguage} from '../language';
import {ErrorNotice} from './primitives';
import {BottomSheet} from './BottomSheet';
import {intakeLabel} from './HistoryScreen';
import {regimenLabel} from '../regimenPresentation';
import {InventoryPanel} from './InventoryPanel';
import {Icon} from './Icon';
import {EmptyState, Row, RowGroup, Screen, VerificationBadge} from '../ui/primitives';

export type MedicineDestination='add-method'|'past-medicines'|'unfinished'|'gallery'|'medicine-detail'|'label'|'manual';

export function isPastCourse(row:{state?:string;course_end_date?:string|null},today:string){return (row.state!==undefined&&['ended','superseded'].includes(row.state))||Boolean(row.course_end_date&&row.course_end_date<today);}

/** Review state plus the schedule, so a patient can see what is safe to act on. */
function summaryHint(row:MedicationSummary,t:(value:string)=>string){
 return `${row.dose_amount??t('Not specified')} ${t(row.dose_unit??'')} · ${row.is_prn?t('As needed'):row.frequency_rule?.local_times.join(', ')??t('Not specified')}`;
}

export function MedicinesHub({medications,versions,onOpen,setupCount=null}:{medications:MedicationSummary[];drafts:RegimenHistoryItem[];setupCount?:number|null;versions:RegimenHistoryItem[];onOpen:(page:MedicineDestination,regimenId?:string)=>void}){
 const {t,preferences}=useLanguage();
 const today=new Intl.DateTimeFormat('en-CA',{timeZone:preferences.timezone,year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
 const current=medications.filter(row=>!isPastCourse(row,today)&&(!row.course_start_date||row.course_start_date<=today));
 const upcoming=medications.filter(row=>!isPastCourse(row,today)&&row.course_start_date&&row.course_start_date>today);
 const pastCount=versions.filter(row=>isPastCourse(row,today)).length;
 const badge=(row:MedicationSummary)=><VerificationBadge sourceBacked={row.source_backed} identityStatus={row.identity_status}/>;
 return <Screen
  className="ui-screen--medicines"
  title="My Medicines"
  lead="What you are taking, and what is known about each medicine."
  actions={<button className="primary" onClick={()=>onOpen('add-method')}>＋ {t('Add medication')}</button>}
 >
  <nav className="medicine-shortcuts" aria-label={t('Medication management shortcuts')}>
   <button className="medicine-shortcut" onClick={()=>onOpen('past-medicines')}><span className="ui-row__icon"><Icon name="clipboard"/></span><span className="ui-row__text"><strong className="ui-row__title">{t('Past courses')}</strong><small className="ui-row__hint">{pastCount} {t('courses')}</small></span><span className="ui-row__end"><Icon name="chevron-right"/></span></button>
   <button className="medicine-shortcut" onClick={()=>onOpen('gallery')}><span className="ui-row__icon"><Icon name="image"/></span><span className="ui-row__text"><strong className="ui-row__title">{t('Photos and evidence')}</strong><small className="ui-row__hint">{t('Manage source photos and evidence')}</small></span><span className="ui-row__end"><Icon name="chevron-right"/></span></button>
   <button className="medicine-shortcut" onClick={()=>onOpen('unfinished')}><span className="ui-row__icon"><Icon name="alert"/></span><span className="ui-row__text"><strong className="ui-row__title">{t('Finish medication setup')}</strong><small className="ui-row__hint">{setupCount===null?t('View saved source registrations'):`${setupCount} ${t('awaiting review')}`}</small></span><span className="ui-row__end"><Icon name="chevron-right"/></span></button>
  </nav>
  <div className="medicines-courses"><RowGroup title="Currently taking">
   {current.length?current.map(row=><Row key={row.regimen_id} title={row.display_name} hint={summaryHint(row,t)} end={<span className="medicine-row-end">{badge(row)}<Icon name="chevron-right"/></span>} onClick={()=>onOpen('medicine-detail',row.regimen_id)}/>)
    :<EmptyState icon="pill" title="No current medication plans." text="Add a medication, review the instructions from your label or pharmacist, and activate the plan. Only a reviewed plan appears in Today."/>}
  </RowGroup>
  {upcoming.length?<RowGroup title="Upcoming courses">{upcoming.map(row=><Row key={row.regimen_id} title={row.display_name} hint={`${t('Course start date')}: ${row.course_start_date}`} end={badge(row)} onClick={()=>onOpen('medicine-detail',row.regimen_id)}/>)}</RowGroup>:null}
  </div>
 </Screen>;
}

export function AddMethodScreen({onOpen}:{onOpen:(page:'label'|'manual')=>void}){
 const {t}=useLanguage();
 return <Screen title="Add medication" lead="Choose how you want to record this medicine. You will review everything before it is activated.">
  <RowGroup>
   <Row icon="camera" title="Read medication information" hint="Add a package photo now and supplement the label later" onClick={()=>onOpen('label')}/>
   <Row icon="clipboard" title="Add manually" hint="Enter your medication and reviewed instructions" onClick={()=>onOpen('manual')}/>
  </RowGroup>
  <p className="notice">{t('A photo is evidence for review. It never confirms what is inside a medicine.')}</p>
 </Screen>;
}

/**
 * Medication record, in four deliberately separate parts:
 * what the product is, what you were told to take, the evidence behind it, and
 * the reports you have made. They are never merged into one list of facts.
 */
export function MedicationDetail({row,summary,onHistory,onGallery,onCheck,onEdit,onChanged,onAssistant,versions=[]}:{row:RegimenHistoryItem;summary?:MedicationSummary|undefined;onEdit?:()=>void;onChanged?:()=>void;onAssistant?:()=>void;versions?:RegimenHistoryItem[];onHistory:()=>void;onGallery:()=>void;onCheck:()=>void}){
 const {t,language,preferences}=useLanguage();
 const [stopping,setStopping]=useState(false),[busy,setBusy]=useState(false);
 const [history,setHistory]=useState<DoseHistoryResponse|null>(null),[error,setError]=useState<unknown>(null);
 useEffect(()=>{let live=true;void api.doseHistory(row.regimen_id).then(value=>{if(live)setHistory(value);}).catch(caught=>{if(live)setError(caught);});return()=>{live=false;};},[row.regimen_id]);
 /**
  * Product strength belongs to the product identity, which lives on the medication
  * summary — not on the regimen row. Reading it off `row` would silently show
  * "not recorded" for every medicine.
  */
 const basis=summary?.dose_basis??null;
 const strength=basis?.strength_text;
 const form=basis?.form||basis?.formulation;
 return <Screen title={row.display_name} actions={<><button className="primary" onClick={onCheck}>{t('Compare a pill photo')}</button><button onClick={onHistory}>{t('My History')}</button></>}>
  <div className="record-status"><VerificationBadge state={row.state}/></div>

  <section className="card">
   <h2 className="card__title">{t('What this medicine is')}</h2>
   <p className="record-line">{strength?`${t('Product strength')}: ${strength}`:t('Strength not recorded')}</p>
   {form?<p className="record-line">{t('Form')}: {form}</p>:null}
   <p className="notice">{t('The product identity is recorded separately from your plan and from your reports.')}</p>
  </section>

  <section className="card">
   <h2 className="card__title">{t('What you were told to take')}</h2>
   <p className="dose-name">{row.dose_amount??t('Not specified')} {t(row.dose_unit??'')}</p>
   <p className="record-line">{row.is_prn?t('As needed'):row.local_times.join(', ')}</p>
   <p className="record-line">{row.food_instruction?.split('; ').map(t).join(' · ')??t('Not specified')}</p>
   <p className="record-line">{t('Course')}: {row.course_start_date??t('Not specified')} → {row.course_end_date??t('Not specified')}</p>
   <details><summary>{t('Medication plan history')}</summary><p className="notice">{t('A plan update does not necessarily start a new treatment course.')}</p>{versions.filter(version=>version.medication_id===row.medication_id).map(version=><p className="record-line" key={version.regimen_id}>{regimenLabel(version,t,language==='zh'?'zh-CN':'en-SG',preferences.timezone)} · {version.local_times.join(', ')}<br/>{t('Course')}: {version.course_start_date??t('Not specified')} → {version.course_end_date??t('Not specified')}</p>)}</details>
  </section>

  <section className="card">
   <h2 className="card__title">{t('Photos and evidence')}</h2>
   <p className="notice">{t('Photos support review. They do not confirm the contents of a medicine or that it is safe to take.')}</p>
   <Row icon="image" title="Personal gallery" hint="Photos and reference availability" onClick={onGallery}/>
  </section>

  <section className="card">
   <h2 className="card__title">{t('Your reports')}</h2>
   {history?.entries.slice(-5).map((entry,index)=><p className="record-line" key={index}>{new Date(entry.due_at??entry.event_time??'').toLocaleString(language==='zh'?'zh-CN':'en-SG',{timeZone:preferences.timezone})} · {t(intakeLabel(entry.intake_status))}</p>)}
   <p className="notice">{t('A report records what you told the app. It is not proof that a medicine was swallowed.')}</p>
  </section>

  <InventoryPanel medicationId={row.medication_id}/>

  {onAssistant?<button className="assistant-entry" onClick={onAssistant}>{t('Ask about this medication')}</button>:null}

  {row.state==='active'?<><p className="notice">{t('To replace this plan, first stop the previous recorded plan in the app. Follow your clinician’s instructions.')}</p><div className="actions"><button className="danger" onClick={()=>{setError(null);setStopping(true);}}>{t('Stop this recorded plan')}</button></div></>:null}
  {row.state==='ended'||row.state==='superseded'?<button onClick={onEdit}>{t('Review a new plan version')}</button>:null}
  {stopping?<BottomSheet title={t('Stop this recorded plan?')} busy={busy} onCancel={()=>setStopping(false)}><p>{t("This stops reminders in MediThread and keeps past records. It does not advise changing your medication. Follow your clinician's instructions.")}</p><p>{t('Previously imported calendar events must be updated or removed in your calendar app.')}</p><button className="primary" disabled={busy} onClick={()=>{setBusy(true);void api.endPlan(row.regimen_id).then(()=>{setStopping(false);onChanged?.();}).catch(setError).finally(()=>setBusy(false));}}>{t('Confirm stop')}</button>{error?<ErrorNotice error={error}/>:null}<button disabled={busy} onClick={()=>setStopping(false)}>{t('Cancel')}</button></BottomSheet>:null}

  <details><summary>{t('Source and review information')}</summary><p>{t(row.state==='draft'||row.state==='pending_clarification'?'This medication needs review before its schedule is enabled.':'This plan was activated after patient review. Changes require a new reviewed version.')}</p><p>{t('Medication instructions are stored separately from visual evidence. Photos do not confirm ingestion.')}</p></details>
  {error&&!stopping?<ErrorNotice error={error}/>:null}
 </Screen>;
}
