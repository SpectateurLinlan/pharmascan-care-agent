import type {HistoryCatalogue,HistoryPlan} from './api/client';

export function historyPlanLabel(row:HistoryPlan,t:(s:string)=>string,locale:string,zone:string):string{
 const date=(value:string)=>new Date(value).toLocaleDateString(locale,{timeZone:zone});
 const dose=row.dose_amount!==null&&row.dose_unit?`${t('Per dose')}: ${row.dose_amount} ${t(row.dose_unit)}`:'';
 const status=row.state==='active'?'Enabled plan':row.state==='ended'?'Ended plan':row.state==='superseded'?'Superseded plan':'Plan awaiting review';
 const rule=row.frequency;
 const weekdays=rule?.days_of_week.map(day=>t(['','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'][day]??'')).filter(Boolean).join(', ');
 const frequency=row.is_prn?t('As needed'):rule?.kind==='interval'&&rule.every_hours?`${t('Every hours')}: ${rule.every_hours}`:rule?[rule.kind==='weekly'?weekdays:t('Daily'),rule.local_times.join(', ')].filter(Boolean).join(' '):t('Frequency not recorded');
 const strength=row.strength_text?`${t(row.dosage_form==='tablet'?'Strength per tablet':row.dosage_form==='capsule'?'Strength per capsule':'Recorded strength')}: ${row.strength_text}`:'';
 return [strength,row.dosage_form?t(row.dosage_form):'',dose,frequency,row.effective_from?`${t('Effective from')}: ${date(row.effective_from)}`:t('Start date not recorded'),row.effective_to?`${t('Effective until')}: ${date(row.effective_to)}`:'',t(status),row.patient_edited?t('Edited'):''].filter(Boolean).join(' \u00b7 ');
}

/** Name-based browsing only: preserve every underlying registration and plan ID. */
export function historyName(value:string){return value.normalize('NFKC').trim().replace(/\s+/g,' ').toLowerCase();}
export function historyMedicationOptions(data:HistoryCatalogue,t:(s:string)=>string){
 const groups=new Map<string,{id:string;name:string;label:string;medication_ids:string[]}>();
 for(const med of data.medications){const key=historyName(med.display_name),group=groups.get(key);if(group)group.medication_ids.push(med.id);else groups.set(key,{id:key,name:med.display_name,label:t(med.display_name),medication_ids:[med.id]});}
 return [...groups.values()].sort((a,b)=>a.label.localeCompare(b.label));
}
