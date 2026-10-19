import {observationText} from '../summaryPresentation';
import {SummaryOverview} from './SummaryOverview';
import {regimenLabel} from '../regimenPresentation';
import {useEffect,useState} from 'react';
import {api,type RegimenHistoryItem,type ReviewSummary} from '../api/client';
import {useLanguage} from '../language';
import {Card,ErrorNotice} from './primitives';
import {ReportDetails} from './ReportDetails';
import {Screen} from '../ui/primitives';

export function ReviewSummaryScreen({period,regimens}:{period:'week'|'month'|'course';regimens:RegimenHistoryItem[]}){
 const {t,language,preferences}=useLanguage();const [regimen,setRegimen]=useState(regimens.find(row=>row.effective_from)?.regimen_id??''),[data,setData]=useState<ReviewSummary|null>(null),[error,setError]=useState<unknown>(null),[notice,setNotice]=useState('');
 useEffect(()=>{let live=true;setData(null);setError(null);if(period==='course'&&!regimen)return;void api.reviewSummary(period,period==='course'?regimen:undefined).then(value=>{if(live)setData(value);}).catch(caught=>{if(live)setError(caught);});return()=>{live=false;};},[period,regimen]);
 const date=(value:string)=>new Date(value).toLocaleString(language==='zh'?'zh-CN':'en-SG',{timeZone:data?.timezone??preferences.timezone});
 function reportText(){if(!data)return '';return [`MediThread — ${t('Medication and health summary')}`,`${date(data.window_start)} → ${date(data.window_end)}`,`${t('Generated')}: ${date(data.generated_at)}`,`${t('Patient reported taken')}: ${data.reported_taken}`,`${t('Patient reported not taken')}: ${data.reported_not_taken}`,`${t('Patient is unsure')}: ${data.unsure}`,...data.medications.map(row=>`${row.name}: ${row.dose_amount??t('Not specified')} ${row.dose_unit??''}; ${row.is_prn?t('As needed'):row.local_times.join(', ')}; ${t('No report')}: ${row.without_report}`),t('My health notes'),...data.observations.map(row=>`${date(row.occurred_at)}: ${observationText(row)}`),...data.questions.map(t),t(data.coverage_note)].join('\n');}
 return <Screen title="Medication and health summary" className="records-detail records-report"><Card title={period==='week'?'This week':period==='month'?'This month':'Selected medication plan'}>
 {period==='course'?<p className="notice">{t('A plan update does not necessarily start a new treatment course. This summary covers the selected plan only.')}</p>:null}
 {period==='course'?<label className="field">{t('Choose a medication plan')}<select className="record-plan-select" value={regimen} onChange={event=>setRegimen(event.target.value)}>{regimens.filter(row=>row.effective_from).map(row=><option key={row.regimen_id} value={row.regimen_id}>{regimenLabel(row,t,language==='zh'?'zh-CN':'en-SG',preferences.timezone)}</option>)}</select></label>:null}
 {error?<ErrorNotice error={error}/>:null}{!data&&!error?<p role="status">{t(period==='course'&&!regimen?'No reviewed course available.':'Loading your summary…')}</p>:null}
 {data?<section className="print-report report-reading"><p>{t('Record-based report')}</p><p>{date(data.window_start)} → {date(data.window_end)}</p><p className="notice">{t('Generated')}: {date(data.generated_at)} · {data.timezone}</p><SummaryOverview data={data}/>
 <ReportDetails>
 <p className="notice">{t(data.coverage_note)}</p>
 <h3>{t('Medication plans')}</h3>{data.medications.length?data.medications.map(row=><article className="health-note" key={row.regimen_id}><strong>{row.name}</strong><p>{row.dose_amount??t('Not specified')} {t(row.dose_unit??'')} · {row.is_prn?t('As needed'):row.local_times.join(', ')}</p><p>{row.course_start??t('Not specified')} → {row.course_end??t('Not specified')}</p><p>{t('Stored scheduled doses')}: {row.recorded_occurrences} · {t('No report')}: {row.without_report}</p></article>):<p>{t('No applicable medication plans in this window.')}</p>}
 <h3>{t('My health notes')}</h3>{data.observations.length?data.observations.map(row=><p key={row.id}>{date(row.occurred_at)} · {observationText(row)}</p>):<p>{t('No health notes yet. You can record how you feel from Health notes.')}</p>}
 </ReportDetails>
 <div className="report-actions no-print"><button onClick={()=>{if(!navigator.clipboard){setNotice('Copy is unavailable. Use export instead.');return;}void navigator.clipboard.writeText(reportText()).then(()=>setNotice('Summary copied. Share it only with someone you choose.')).catch(()=>setNotice('Copy is unavailable. Use export instead.'));}}>{t('Copy summary')}</button><button onClick={()=>window.print()}>{t('Print')}</button><button onClick={()=>{const url=URL.createObjectURL(new Blob([reportText()],{type:'text/plain;charset=utf-8'}));const link=document.createElement('a');link.href=url;link.download='medithread-summary.txt';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}}>{t('Export summary')}</button></div>{notice?<p role="status">{t(notice)}</p>:null}
 </section>:null}</Card></Screen>;
}
