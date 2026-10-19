import {useEffect,useState,type ReactNode} from 'react';
import type {MedicationSummary} from '../api/client';
import {useLanguage} from '../language';
import {Icon} from './Icon';

/** Compact overview; only the selected authenticated dose flow performs reads. */
export function TodayMedicationCarousel({medications,focusRegimenId,children,embedded=false}:{medications:MedicationSummary[];focusRegimenId:string|null;children:(medication:MedicationSummary)=>ReactNode;embedded?:boolean}){
 const {t}=useLanguage();const [selected,setSelected]=useState<string|null>(focusRegimenId);
 useEffect(()=>{if(focusRegimenId)setSelected(focusRegimenId);},[focusRegimenId]);
 const duplicateNames=new Set(medications.map(row=>row.display_name.trim().toLowerCase())).size<medications.length;
 const active=medications.find(row=>row.regimen_id===selected)??medications[0];
 const content=<>{duplicateNames?<p className="notice" role="status">{t('Multiple recorded plans have the same medicine name. Review them before reporting a dose; the app has not combined their instructions.')}</p>:null}
 {medications.length>1?<div className="medicine-overview medicine-list" role="group" aria-label={t('All current medicines')}>
 {medications.map(row=><button key={row.regimen_id} className="medicine-chip medicine-list-row" aria-pressed={row.regimen_id===active?.regimen_id} onClick={()=>setSelected(row.regimen_id)}><span className="medicine-time">{row.is_prn?t('As needed'):row.frequency_rule?.local_times.join(' · ')||t('Not specified')}</span><span className="medicine-label"><strong>{row.display_name}</strong>{' '}<small>{row.dose_basis?.strength_text?`${row.dose_basis.strength_text} · `:''}{t('Per dose')}: {row.dose_amount??t('Not specified')} {t(row.dose_unit??'')}{medications.filter(med=>med.display_name===row.display_name).length>1?` · ${t('Course')}: ${row.course_start_date??t('Not specified')} → ${row.course_end_date??t('Not specified')}`:''}</small></span><Icon name="chevron-right"/></button>)}
 </div>:null}{active?<div className="medicine-current">{children(active)}</div>:null}</>;
 if(embedded)return <div className="today-overview today-overview--embedded" aria-label={t("Today's medication")}>{content}</div>;
 return <section className="today-overview card" aria-label={t("Today's medication")}><div className="today-overview-heading"><h2>{t("Today's medication")}</h2>{medications.length>1?<span>{medications.length} {t('medication plans')}</span>:null}</div>{content}</section>;
}
