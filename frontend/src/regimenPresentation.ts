import type {RegimenHistoryItem} from './api/client';
import {regimenStatusLabelKey} from './regimenHistoryModel';

/** Presentation only: a plan version is not a separate treatment course.
 * Dose is labelled explicitly; the history DTO does not expose product strength.
 */
export function regimenLabel(row:RegimenHistoryItem,t:(key:string)=>string,locale:string,timeZone:string):string {
 const start=row.effective_from;
 const effective=start?new Intl.DateTimeFormat(locale,{dateStyle:'medium',timeStyle:'short',timeZone}).format(new Date(start)):t('Start date not recorded');
 const status=regimenStatusLabelKey(row,timeZone);
 const dose=row.dose_amount!==null&&row.dose_unit?`${t('Dose')}: ${row.dose_amount} ${t(row.dose_unit)}`:null;
 return [row.display_name,dose,`${t('Effective from')}: ${effective}`,t(status)].filter(Boolean).join(' · ');
}
