import {api,type MedicationHistoryPage,type MedicationSummary,type RegimenHistoryItem,type GalleryEntry,type MedicationKnowledge} from '../api/client';
import {useEffect,useRef,useState} from 'react';
import {useLanguage} from '../language';
import {regimenStatusLabelKey} from '../regimenHistoryModel';
import {ErrorNotice} from './primitives';
import {BottomSheet} from './BottomSheet';
import {InventoryPanel} from './InventoryPanel';
import {PrivateEvidencePhoto} from './PrivateEvidencePhoto';
import {Icon} from './Icon';
import {EmptyState, Screen, StatusPill, VerificationBadge} from '../ui/primitives';
import {regimenCourseGroups} from '../regimenHistoryModel';

export type MedicineDestination='past-medicines'|'unfinished'|'gallery'|'medicine-detail'|'medication-inventory'|'label'|'manual';

// The medications endpoint returns active plans. A planned end date does not
// transition the backend lifecycle or make an active plan a historical course.
export function isPastCourse(row:{state?:string;course_end_date?:string|null},today=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Singapore',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date())){return (row.state!==undefined&&['ended','superseded'].includes(row.state))||((!row.state||row.state==='active')&&!!row.course_end_date&&row.course_end_date<today);}

/** Review state plus the schedule, so a patient can see what is safe to act on. */
function summaryHint(row:MedicationSummary,t:(value:string)=>string){
 return `${row.dose_amount??t('Not specified')} ${t(row.dose_unit??'')} · ${row.is_prn?t('As needed'):row.frequency_rule?.local_times.join(', ')??t('Not specified')}`;
}

export function MedicinesHub({medications,versions,onOpen,setupCount=null}:{medications:MedicationSummary[];drafts:RegimenHistoryItem[];setupCount?:number|null;versions:RegimenHistoryItem[];onOpen:(page:MedicineDestination,regimenId?:string)=>void}){
 const {t,preferences}=useLanguage();
 const today=new Intl.DateTimeFormat('en-CA',{timeZone:preferences.timezone,year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
 const current=medications.filter(row=>!isPastCourse(row,today)&&(!row.course_start_date||row.course_start_date<=today));
 const upcoming=medications.filter(row=>!isPastCourse(row,today)&&row.course_start_date&&row.course_start_date>today);
 const pastCount=regimenCourseGroups(versions).length;
 const medicationRow=(row:MedicationSummary,planned=false)=><button type="button" className="medication-list-row" key={row.regimen_id} onClick={()=>onOpen('medicine-detail',row.regimen_id)}>
  <span className="medication-list-row__icon"><Icon name="pill"/></span>
  <span className="medication-list-row__body"><strong>{row.display_name}</strong><small>{planned?`${t('Course start date')}: ${row.course_start_date}`:summaryHint(row,t)}</small></span>
  <span className="medication-list-row__badges">{versions.find(version=>version.regimen_id===row.regimen_id)?.patient_edited?<span className="medication-edited-badge">{t('Edited')}</span>:null}{row.source_backed?<span className="medication-source-badge">{t('Source record')}</span>:null}<Icon name="chevron-right"/></span>
 </button>;
 return <Screen
  className="ui-screen--medicines"
  title="My Medicines"
  lead="View, add and manage your medications."
  headerTrailing={<span className="medicines-header-icon"><Icon name="pill"/></span>}
 >
  <section className="card medication-add-section" aria-labelledby="medication-add-title">
   <header className="medication-add-section__header"><h2 id="medication-add-title">{t('Add medication')}</h2></header>
   <div className="medication-add-actions">
    <button type="button" className="medication-add-action medication-add-action--scan" onClick={()=>onOpen('label')}>
     <Icon name="camera"/><strong>{t('Scan medication document')}</strong><small>{t('Photograph or upload a medication document')}</small>
    </button>
    <button type="button" className="medication-add-action medication-add-action--manual" onClick={()=>onOpen('manual')}>
     <Icon name="clipboard"/><strong>{t('Add manually')}</strong><small>{t('Enter your medication and reviewed instructions')}</small>
    </button>
   </div>
  </section>
  <section className="card current-medications-card" aria-labelledby="current-medications-title">
   <header className="current-medications-card__header"><h2 id="current-medications-title">{t('Currently taking')}</h2><span className="medication-count-badge">{current.length===1?t('1 medicine'):t('{count} medicines').replace('{count}',String(current.length))}</span></header>
   {current.length?<div className="medication-list">{current.map(row=>medicationRow(row))}</div>:<EmptyState icon="pill" title="No current medication plans." text="Add a medication, review the instructions from your label or pharmacist, and activate the plan. Only a reviewed plan appears in Today."/>}
   {upcoming.length?<div className="upcoming-medications"><h3>{t('Upcoming courses')}</h3><div className="medication-list">{upcoming.map(row=>medicationRow(row,true))}</div></div>:null}
  </section>
  {setupCount===null||setupCount>0?<button type="button" aria-label={`${t('Finish medication setup')}${setupCount===null?'':`, ${setupCount} ${t('awaiting review')}`}`} className={`pending-medication-review${setupCount===null?' pending-medication-review--unknown':''}`} onClick={()=>onOpen('unfinished')}>
   <Icon name={setupCount===null?'clipboard':'alert'}/><span><strong>{setupCount===null?t('Finish medication setup'):setupCount===1?t('1 medication setup needs review'):t('{count} medication setups need review').replace('{count}',String(setupCount))}</strong><small>{setupCount===null?t('View saved source registrations'):t('Review medication setup details to keep your records accurate.')}</small></span><Icon name="chevron-right"/>
  </button>:null}
  <nav className="medicine-shortcuts" aria-label={t('Medication management shortcuts')}>
   <button className="medicine-shortcut" onClick={()=>onOpen('past-medicines')}><span className="ui-row__icon"><Icon name="clock"/></span><span className="ui-row__text"><strong className="ui-row__title">{t('Regimen Records')}</strong><small className="ui-row__hint">{pastCount} {t('courses')}</small></span><span className="ui-row__end"><Icon name="chevron-right"/></span></button>
   <button className="medicine-shortcut" onClick={()=>onOpen('gallery')}><span className="ui-row__icon"><Icon name="image"/></span><span className="ui-row__text"><strong className="ui-row__title">{t('Medication Library')}</strong><small className="ui-row__hint">{t('View and manage medication photos, documents and source records')}</small></span><span className="ui-row__end"><Icon name="chevron-right"/></span></button>
  </nav>
 </Screen>;
}

/**
 * Medication record, in four deliberately separate parts:
 * what the product is, what you were told to take, the evidence behind it, and
 * the reports you have made. They are never merged into one list of facts.
 */
export function MedicationDetail({row,summary,onHistory,onGallery,onCheck,onEdit,onChanged,onManageInventory,versions=[]}:{row:RegimenHistoryItem;summary?:MedicationSummary|undefined;onEdit?:()=>void;onChanged?:()=>void;onManageInventory?:()=>void;versions?:RegimenHistoryItem[];onHistory:()=>void;onGallery:()=>void;onCheck:()=>void}){
 const {t,language,preferences}=useLanguage();
 const [stopping,setStopping]=useState(false),[busy,setBusy]=useState(false),[managePlan,setManagePlan]=useState(false);
 const [previewPhoto,setPreviewPhoto]=useState<GalleryEntry['images'][number]|null>(null);
 const carouselRef=useRef<HTMLDivElement>(null);
 const [knowledge,setKnowledge]=useState<MedicationKnowledge|null>(null),[knowledgeLoading,setKnowledgeLoading]=useState(false),[knowledgeError,setKnowledgeError]=useState<unknown>(null);
 const [history,setHistory]=useState<MedicationHistoryPage|null>(null),[products,setProducts]=useState<GalleryEntry[]>([]),[productsLoaded,setProductsLoaded]=useState(false),[productLoadError,setProductLoadError]=useState(false),[error,setError]=useState<unknown>(null);
 useEffect(()=>{let live=true;setHistory(null);void api.medicationHistory({range_kind:'7',medication_id:row.medication_id,regimen_id:row.regimen_id}).then(value=>{if(live)setHistory(value);}).catch(caught=>{if(live)setError(caught);});return()=>{live=false;};},[row.medication_id,row.regimen_id]);
 useEffect(()=>{let live=true;setProductsLoaded(false);setProductLoadError(false);void api.personalGallery().then(value=>{if(live){setProducts(value);setProductsLoaded(true);}}).catch(caught=>{if(live){setError(caught);setProductLoadError(true);setProductsLoaded(true);}});return()=>{live=false;};},[row.medication_id]);
 useEffect(()=>{setKnowledge(null);setKnowledgeError(null);},[row.medication_id]);
 async function loadKnowledge(){setKnowledgeLoading(true);setKnowledgeError(null);try{setKnowledge(await api.medicationKnowledge(row.medication_id,language));}catch(caught){setKnowledgeError(caught);}finally{setKnowledgeLoading(false);}}
 const basis=summary?.dose_basis??null;
 const product=products.find(item=>item.medication.id===row.medication_id);
 const strength=product?.product?.strength??basis?.strength_text;
 const form=product?.product?.dose_form??(basis?.form&&basis.form!=='unknown'?basis.form:null);
 const frequency=summary?.frequency_rule??row.frequency_rule;
 const plannedTimes=row.is_prn?t('As needed'):row.local_times.length?row.local_times.join(', '):t('Not recorded');
 const status=regimenStatusLabelKey(row,preferences.timezone);
 const locale=language==='zh'?'zh-SG':'en-SG';
 const latest=history?.entries.slice(0,3)??[];
 const reported=history?.entries.filter(item=>item.reported)??[];
 const countsComplete=Boolean(history&&!history.next_cursor);
 const relatedPlanVersions=regimenVersionChain(row,versions);
 return <Screen title={row.display_name}>
  <div className="medication-detail-status"><StatusPill tone={row.state==='active'&&status!=='Course Expired'?'ok':'quiet'} label={t(status)}/>{row.state==='active'&&summary?.identity_status==='unverified'?<VerificationBadge state={row.state} identityStatus={summary.identity_status}/>:null}{row.patient_edited?<span className="tag">{t('Patient-edited plan')}</span>:null}</div>

  <section className="card medication-detail-section" aria-labelledby="current-plan-title">
   <h2 id="current-plan-title" className="card__title">{t('Current medication plan')}</h2>
   <dl className="medication-detail-grid">
    <div><dt>{t('Single dose')}</dt><dd>{row.dose_amount??t('Not recorded')} {t(row.dose_unit??'')}</dd></div>
    <div><dt>{t('Times in plan')}</dt><dd>{plannedTimes}</dd></div>
    <div><dt>{t('Frequency')}</dt><dd>{row.is_prn?t('As needed'):frequency?.kind==='interval'?t('Every {count} hours').replace('{count}',String(frequency.every_hours??t('Not recorded'))):frequency?.kind==='weekly'?`${t('Weekly')} · ${frequency.days_of_week.map(day=>t(['','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'][day]??'Not recorded')).join(', ')}`:frequency?.kind==='daily'?t('Daily'):t('Not recorded')}</dd></div>
    <div><dt>{t('Regimen start date')}</dt><dd>{row.course_start_date??t('Not recorded')}</dd></div>
    <div><dt>{t('Regimen end date')}</dt><dd>{row.course_end_date??(row.state==='active'?t('No end date recorded'):t('Not recorded'))}</dd></div>
    <div><dt>{t('Plan provenance')}</dt><dd>{summary?.source_backed?t('Saved medication source'):t('Patient-entered plan')}</dd></div>
   </dl>
   {row.food_instruction?<p className="record-line">{t('Food instructions')}: {row.food_instruction.split('; ').map(t).join(' · ')}</p>:null}
   <div className="medication-detail-actions">{row.state==='active'?<button type="button" onClick={onEdit}>{t('Manage medication plan')}</button>:null}{row.state==='ended'||row.state==='superseded'?<button type="button" onClick={onEdit}>{t('Review a new plan version')}</button>:null}{relatedPlanVersions.length>1?<button type="button" aria-expanded={managePlan} aria-controls="plan-management-details" onClick={()=>setManagePlan(value=>!value)}>{t('View plan changes')}</button>:null}</div>
   {managePlan?<div id="plan-management-details" className="medication-plan-management"><h3>{t('Medication plan history')}</h3>{relatedPlanVersions.filter(version=>version.regimen_id!==row.regimen_id).map(version=><p key={version.regimen_id}>{t(version.state)} · {version.course_start_date??t('Not recorded')} → {version.course_end_date??t('Not recorded')}</p>)}</div>:null}
  </section>

  <section className="card medication-detail-section" aria-labelledby="medication-information-title">
   <h2 id="medication-information-title" className="card__title">{t('Medication information')}</h2>
   <dl className="medication-information-list">
    <div><dt>{t('Medication name')}</dt><dd>{row.display_name}</dd></div>
    <div><dt>{t('Active ingredient')}</dt><dd>{product?.product?.ingredients.length?product.product.ingredients.join(', '):t('Not recorded')}</dd></div>
    <div><dt>{t('Product strength')}</dt><dd>{strength??t('Not recorded')}</dd></div>
    <div><dt>{t('Dosage form')}</dt><dd>{form?t(form):t('Not recorded')}</dd></div>
    <div><dt>{t('Information source')}</dt><dd>{product?.evidence_task_id?t('Source record'):t('Patient record')}</dd></div>
   </dl>
   {product?.evidence_task_id?<button type="button" onClick={()=>onGallery()}>{t('View source information')}</button>:null}
   <div className="medication-knowledge-entry"><header><h3>{t('General medication knowledge')}</h3><span>{t('External reference')}</span></header><p>{t('View source-grounded general information about uses and precautions. This does not identify your product or provide personal dosing instructions.')}</p><button type="button" disabled={knowledgeLoading} onClick={()=>void loadKnowledge()}>{t(knowledgeLoading?'Loading medication knowledge...':'View medication knowledge')}</button>
    {knowledgeError?<div role="alert"><ErrorNotice error={knowledgeError}/><button type="button" disabled={knowledgeLoading} onClick={()=>void loadKnowledge()}>{t('Retry knowledge lookup')}</button></div>:null}
    {knowledge?<div className="medication-knowledge-result" aria-live="polite"><p>{knowledge.general_knowledge?.status==='matched'?(language==='zh'?knowledge.general_knowledge.use_statement_zh??knowledge.general_knowledge.use_statement:knowledge.general_knowledge.use_statement):t(knowledge.general_knowledge?.status==='unavailable'?'Medication knowledge is temporarily unavailable.':'No reliable matching medication knowledge was found.')}</p>
     {knowledge.general_knowledge?.sources.map(source=><details key={source.set_id}><summary>{source.source_name} · {source.market} · {source.effective_time} · v{source.version}</summary><p><a href={source.url} target="_blank" rel="noreferrer">{source.url}</a></p><small>{t('Source identifiers')}: {source.set_id} · {source.label_id}</small>{source.sections.map(section=><p key={section.field}><strong>{section.field.replaceAll('_',' ')}</strong><br/>{section.text}{section.truncated?` ${t('Excerpt shortened')}`:''}</p>)}</details>)}
     <p className="medication-detail-note">{knowledge.general_knowledge?.regulatory_note??knowledge.patient_safe_summary}</p>
    </div>:null}
   </div>
  </section>

  <InventoryPanel medicationId={row.medication_id} {...(onManageInventory?{onManage:onManageInventory}:{})}/>

  <section className="card medication-detail-section" aria-labelledby="medication-history-title">
   <header className="medication-detail-section__header"><h2 id="medication-history-title" className="card__title">{t('Medication history')}</h2><span>{t('Last 7 days')}</span></header>
   {history?<div className="medication-history-summary">
    <div><span>{t('Reported taken')}</span><strong>{countsComplete?reported.filter(item=>item.intake_status==='reported_taken').length:t('At least {count}').replace('{count}',String(reported.filter(item=>item.intake_status==='reported_taken').length))}</strong></div>
    <div><span>{t('Unconfirmed events')}</span><strong>{countsComplete?history.entries.filter(item=>!item.reported||item.intake_status==='unsure').length:t('At least {count}').replace('{count}',String(history.entries.filter(item=>!item.reported||item.intake_status==='unsure').length))}</strong></div>
    {!history.entries.length?<p>{t('No records in this range.')}</p>:latest.map(item=><p className="medication-history-event" key={item.id}><span>{new Date(item.sort_time).toLocaleString(locale,{timeZone:preferences.timezone})}</span><strong>{t(item.reported?(item.intake_status==='reported_taken'?'You reported taking this dose':item.intake_status==='reported_not_taken'?'You reported not taking this dose':'You were unsure'): 'This dose has no record of whether you took it yet.')}</strong></p>)}
    <p className="medication-detail-note">{t('A report records what you told the app. It is not proof that a medicine was swallowed.')}</p>
   </div>:<p role="status">{t('Loading your history...')}</p>}
   <button type="button" onClick={onHistory}>{t('View all records')} <Icon name="chevron-right"/></button>
  </section>

  <section className="card medication-detail-section" aria-labelledby="medication-evidence-title">
   <header className="medication-detail-section__header"><h2 id="medication-evidence-title" className="card__title">{t('Photos and evidence')}</h2><span>{product?t('{count} reference photos').replace('{count}',String(product.images.length)):productsLoaded&&!productLoadError?t('{count} reference photos').replace('{count}','0'):productLoadError?t('Reference photo count unavailable'):t('Loading medication photos...')}</span></header>
   <p className="medication-detail-note">{t('Photos support review. They do not confirm the contents of a medicine or that it is safe to take.')}</p>
   {product?.images.length?<div ref={carouselRef} className="medication-photo-carousel" role="region" tabIndex={0} aria-label={t('Medication reference photos')} onKeyDown={event=>{if(event.key==='ArrowRight'||event.key==='ArrowLeft'){event.preventDefault();carouselRef.current?.scrollBy({left:(event.key==='ArrowRight'?1:-1)*(carouselRef.current.clientWidth*0.8),behavior:'smooth'});}}}>
    {product.images.map((photo,index)=><figure key={photo.id} className="medication-photo-carousel__item"><PrivateEvidencePhoto photo={photo} onOpen={()=>setPreviewPhoto(photo)}/><figcaption>{t(photo.image_kind==='loose_pill'?'Loose pill':photo.image_kind==='blister'?'Blister':'Packaging or source')} · {new Date(photo.created_at).toLocaleDateString(locale,{timeZone:preferences.timezone})}{index===0?<span className="sr-only"> · {t('First photo')}</span>:null}</figcaption></figure>)}
   </div>:productsLoaded&&!productLoadError?<p>{t('No reference photos linked yet.')}</p>:!productLoadError?<p role="status">{t('Loading medication photos...')}</p>:null}
   {product?.evidence_task_id?<p>{t('Source information is linked')}</p>:productsLoaded&&!productLoadError?<p>{t('No source information linked')}</p>:productLoadError?<p>{t('Source information unavailable')}</p>:null}
   <div className="medication-detail-actions"><button type="button" onClick={onGallery}>{t('Open medication gallery')} <Icon name="chevron-right"/></button><button type="button" onClick={onCheck}>{t('Compare a pill photo')}</button></div>
  </section>

  <section className="medication-regimen-management" aria-labelledby="regimen-management-title"><h2 id="regimen-management-title">{t('Regimen management')}</h2>{row.state==='active'?<><p>{t('Stopping tracking keeps past medication records. Follow your clinician’s instructions about your medicine.')}</p><button className="danger" onClick={()=>{setError(null);setStopping(true);}}>{t('Stop tracking this regimen')}</button></>:<p>{t(status)}</p>}</section>
  {stopping?<BottomSheet title={t('Stop this recorded plan?')} busy={busy} onCancel={()=>setStopping(false)}><p>{t("This stops reminders in MediThread and keeps past records. It does not advise changing your medication. Follow your clinician's instructions.")}</p><p>{t('Previously imported calendar events must be updated or removed in your calendar app.')}</p><button className="primary" disabled={busy} onClick={()=>{setBusy(true);void api.endPlan(row.regimen_id).then(()=>{setStopping(false);onChanged?.();}).catch(setError).finally(()=>setBusy(false));}}>{t('Confirm stop')}</button>{error?<ErrorNotice error={error}/>:null}<button disabled={busy} onClick={()=>setStopping(false)}>{t('Cancel')}</button></BottomSheet>:null}
  {previewPhoto?<BottomSheet title={t('Photo preview')} onCancel={()=>setPreviewPhoto(null)}><div className="medication-photo-preview"><PrivateEvidencePhoto photo={previewPhoto}/><p>{t(previewPhoto.image_kind==='loose_pill'?'Loose pill':previewPhoto.image_kind==='blister'?'Blister':'Packaging or source')} · {new Date(previewPhoto.created_at).toLocaleDateString(locale,{timeZone:preferences.timezone})}</p><p>{t('This image is linked to this medication as reference evidence. It does not confirm ingestion.')}</p><button onClick={()=>setPreviewPhoto(null)}>{t('Close photo preview')}</button></div></BottomSheet>:null}

  {error&&!stopping?<ErrorNotice error={error}/>:null}
 </Screen>;
}

function regimenVersionChain(selected:RegimenHistoryItem,versions:RegimenHistoryItem[]){
 const related=new Map([[selected.regimen_id,selected]]);
 let changed=true;
 while(changed){
  changed=false;
  for(const version of versions){
   if(version.medication_id!==selected.medication_id||related.has(version.regimen_id))continue;
   if(version.supersedes_id&&related.has(version.supersedes_id)){related.set(version.regimen_id,version);changed=true;continue;}
   if([...related.values()].some(item=>item.supersedes_id===version.regimen_id)){related.set(version.regimen_id,version);changed=true;}
  }
 }
 return [...related.values()].sort((a,b)=>a.version_no-b.version_no||a.regimen_id.localeCompare(b.regimen_id));
}
