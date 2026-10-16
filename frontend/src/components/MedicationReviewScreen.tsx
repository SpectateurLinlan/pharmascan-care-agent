import {useEffect,useState} from 'react';
import {api} from '../api/client';
import type {MedicationCareReview,ObservationTrend} from '../api/care';
import {useLanguage} from '../language';
import {Card,ErrorNotice} from './primitives';

function Trend({data}:{data:ObservationTrend}){
 const {t,language,preferences}=useLanguage();const values=data.points.map(row=>row.value),min=Math.min(...values),max=Math.max(...values);
 const start=new Date(data.start).getTime(),end=new Date(data.end).getTime();
 const points=data.points.map(row=>`${10+280*(new Date(row.at).getTime()-start)/(end-start||1)},${90-70*(row.value-min)/(max-min||1)}`).join(' ');
 return <section><h3>{t(data.kind)} · {data.unit}</h3><p>{data.count} {t('records')} · {t('Observed change')}: {data.change===null?t('Insufficient data'):data.change.toFixed(2)} {data.unit}</p>
 {data.count>=2?<svg role="img" aria-label={`${t(data.kind)} ${t('Recorded measurements')}`} viewBox="0 0 300 110" className="health-trend"><polyline points={points} fill="none" stroke="currentColor" strokeWidth="3"/></svg>:null}
 <details><summary>{t('Recorded measurements')}</summary>{data.points.map((row,index)=><p key={index}>{new Date(row.at).toLocaleString(language==='zh'?'zh-CN':'en-SG',{timeZone:preferences.timezone})}: {row.value}{row.secondary_value===null?'':` / ${row.secondary_value}`} {data.unit}</p>)}</details><p className="notice">{t('Irregular sampling; missing measurements are unknown. These changes do not establish a medication effect.')}</p></section>;
}

export function MedicationReviewScreen(){
 const {t,language}=useLanguage();const [days,setDays]=useState<7|30>(30),[data,setData]=useState<MedicationCareReview|null>(null),[error,setError]=useState<unknown>(null),[questions,setQuestions]=useState('');
 useEffect(()=>{let live=true;setData(null);setError(null);void api.medicationCareReview(days).then(value=>{if(live)setData(value);}).catch(caught=>{if(live)setError(caught);});return()=>{live=false;};},[days]);
 function exportReview(){if(!data)return;const content=[`MediThread — ${t('Medication review preparation')}`,`${data.generated_at} · ${data.timezone}`,t('Patient-reported information; review with your healthcare professional.'),
 `${data.summary.window_start} → ${data.summary.window_end}`,...data.summary.medications.map(row=>`${row.name}: ${row.state} v${row.version}; ${row.dose_amount??'?'} ${row.dose_unit??''} · ${row.is_prn?t('As needed'):row.local_times.join(', ')||t('Not specified')}; ${t('No report')}: ${row.without_report}`),
 `${t('Patient reported taken')}: ${data.summary.reported_taken}; ${t('Patient reported not taken')}: ${data.summary.reported_not_taken}; ${t('Patient is unsure')}: ${data.summary.unsure}`,
 ...data.summary.observations.map(row=>`${row.occurred_at}: ${row.description}`),...data.barriers.map(row=>`${t(row.category)}: ${row.description}; ${row.chosen_action}`),
 ...data.source_records.map(row=>row.name+'; '+t('Source document')+': '+(row.source_document_id??t('Unknown'))+'; '+t(row.source_type??'Unknown')+'; '+t(row.review_status??'Unknown')+'; v'+row.version+' '+t(row.state)),...data.inventory.map(row=>(data.summary.medications.find(med=>med.medication_id===row.medication_id)?.name??t('Registered medicine'))+': '+`${t('Estimated remaining')}: ${row.estimated_remaining??t('Unknown')} ${row.unit??''}`),
 ...data.trends.map(row=>`${t(row.kind)} (${row.unit}): ${row.points.map(point=>`${point.at}: ${point.value}${point.secondary_value===null?'':`/${point.secondary_value}`}`).join('; ')}`),
 ...data.follow_ups.map(row=>`${row.title} · ${row.due_at} · ${t(row.status)}`),...data.questions.map(t),questions,
 data.summary.coverage_note,data.adherence_denominator,data.source_note].join('\n');
 const url=URL.createObjectURL(new Blob([content],{type:'text/plain;charset=utf-8'})),link=document.createElement('a');link.href=url;link.download='medithread-medication-review.txt';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
 return <Card title="Medication review preparation"><label className="field">{t('Observation window')}<select value={days} onChange={event=>setDays(Number(event.target.value) as 7|30)}><option value={7}>{t('Last 7 days')}</option><option value={30}>{t('Last 30 days')}</option></select></label>
 {error?<ErrorNotice error={error}/>:null}{!data&&!error?<p>{t('Loading records…')}</p>:data?<><p className="notice">{t('Patient-reported information; review with your healthcare professional.')}</p><h3>{t('Current medications and changes')}</h3>{data.summary.medications.map(row=><p key={row.regimen_id}>{row.name} · {t(row.state)} · {t('version')} {row.version} · {row.dose_amount??t('Unknown')} {t(row.dose_unit??'')} · {row.is_prn?t('As needed'):row.local_times.join(', ')||t('Not specified')}<br/>{row.course_start??t('Not specified')} → {row.course_end??t('Not specified')} · {t('No report')}: {row.without_report}</p>)}
 <details><summary>{t('Source and regimen history')}</summary>{data.source_records.map(row=><p key={row.regimen_id}>{row.name} · {t('version')} {row.version} · {t(row.state)} · {t(row.source_type??'Unknown')} · {t(row.review_status??'Unknown')}<br/>{t('Source document')}: {row.source_document_id??t('Unknown')}</p>)}</details>
 <h3>{t('Patient-reported adherence')}</h3><p>{t('Patient reported taken')}: {data.summary.reported_taken} · {t('Patient reported not taken')}: {data.summary.reported_not_taken} · {t('Patient is unsure')}: {data.summary.unsure}</p><p className="notice">{t('Only stored generated occurrences are counted. No report is not a missed dose. No adherence percentage is inferred.')}</p>
 <h3>{t('Medication difficulties')}</h3>{data.barriers.map(row=><p key={row.id}>{t(row.category)} · {row.description} · {row.chosen_action}</p>)}
 <h3>{t('Health observations and trends')}</h3>{data.trends.length?data.trends.map(row=><Trend key={row.kind+row.unit} data={row}/>):<p>{t('Insufficient measurements for a numeric trend.')}</p>}{data.summary.observations.map(row=><p key={row.id}>{new Date(row.occurred_at).toLocaleDateString(language==='zh'?'zh-CN':'en-SG',{timeZone:data.timezone})} · {row.description}</p>)}
 <h3>{t('Inventory and refill concerns')}</h3>{data.inventory.map(row=><p key={row.medication_id}>{data.summary.medications.find(med=>med.medication_id===row.medication_id)?.name??t('Registered medicine')} · {t('Estimated remaining')}: {row.estimated_remaining??t('Unknown')} {t(row.unit??'')}{row.low_stock?` · ${t('Low stock')}`:''}</p>)}
 <h3>{t('Unresolved follow-ups')}</h3>{data.follow_ups.map(row=><p key={row.id}>{row.title} · {new Date(row.due_at).toLocaleString(language==='zh'?'zh-CN':'en-SG',{timeZone:data.timezone})} · {t(row.status)}</p>)}
 <h3>{t('Questions for your pharmacist or doctor')}</h3>{data.questions.map(question=><p key={question}>{t(question)}</p>)}<label className="field">{t('Your additional questions (included in export)')}<textarea maxLength={2000} value={questions} onChange={event=>setQuestions(event.target.value)}/></label><button className="primary" onClick={exportReview}>{t('Export medication review')}</button><p className="notice">{t('Downloaded to your device only. Review before choosing to share; nothing is sent automatically.')}</p></>:null}
 </Card>;
}
