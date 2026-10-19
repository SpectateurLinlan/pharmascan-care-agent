import type {SourcePreview} from '../api/client';
import {useLanguage} from '../language';
import {SourceReviewHints} from './SourceReviewHints';

/**
 * Medication understanding: what a source actually said, and where it said it.
 *
 * Two things this component must never do:
 *   1. invent a value the source did not return — a missing field is shown as
 *      missing, never guessed;
 *   2. present a general, label-derived statement as if it were a personal
 *      instruction or a diagnosis.
 *
 * So the label's "used for" statement is shown as its own visible block, with
 * the exact source line beside it, while the patient's own reviewed directions
 * stay above it under "Read from the label".
 */
export function PrintedLabelEvidence({candidate}: {candidate:SourcePreview['candidates'][number]}) {
 const {t}=useLanguage();const evidence=candidate.regimen_evidence,parts=evidence.instructions;
 const unknown=t('Not printed or not read. Please check the original label.');
 const rows:Array<[string,string|null|undefined]>=[
  ['Dose amount',parts?.dose?`${parts.dose.amount}${parts.dose.amount_max!=null?`–${parts.dose.amount_max}`:''} ${t(parts.dose.unit??'')}`:null],
  ['doses per day',parts?.times_per_day?.toString()],['Every N hours',parts?.every_hours?.toString()],
  ['As needed',parts?.as_needed?t('As needed'):null],
  ['Time wording',parts?.times_of_day.map(value=>t(value)).join(', ')],
  ['Food instructions',parts?.food?t(parts.food):null],['Printed duration',parts?.duration],['Printed daily maximum',parts?.max_per_day],
 ];
 return <div className="printed-label-evidence"><h4>{t('Read from the label')}</h4>
 <p>{evidence.directions?.value??parts?.text??t('No personal directions were returned.')}</p>
 <SourceReviewHints candidates={[candidate]}/>
 <dl className="source-instructions">{rows.map(([label,value])=><div key={label}><dt>{t(label)}</dt><dd>{value||unknown}</dd></div>)}</dl>
 <p className="notice">{t('Frequency does not specify clock times. Label dates and expiry are not course dates.')}</p>
 {evidence.cautions?.map((item,index)=><p key={index}>{item.value}</p>)}
 {candidate.list_comparison?<p>{t(candidate.list_comparison.status==='different_strength'?'Possible different strength — review both sources.':candidate.list_comparison.status==='same_medicine'?'Possibly already registered — review before linking.':candidate.list_comparison.status==='contains_listed'?'May contain an ingredient in your records.':'May be a new medicine — review the source.')}</p>:null}

 {/* The medicine's general use, straight from the matched label excerpt. It is
     rendered only when the source returned it, and the source line travels with
     it so a patient or pharmacist can check where it came from. */}
 {evidence.indication?<section className="label-indication">
  <h5 className="label-indication__title">{t('What this medicine is used for')}</h5>
  <p className="label-indication__value">{evidence.indication.value}</p>
  <p className="label-indication__source">{t('From the label')}: {evidence.indication.line}</p>
  <p className="notice">{t('This is general information from the medicine label, not a diagnosis or advice about your own treatment.')}</p>
 </section>:null}

 <details><summary>{t('Printed evidence')}</summary>{parts?<blockquote>{parts.line}</blockquote>:null}{evidence.directions?<blockquote>{evidence.directions.line}</blockquote>:null}{evidence.supplied_quantity?<p>{t('Quantity supplied (not per dose)')}: {evidence.supplied_quantity.value} — {evidence.supplied_quantity.line}</p>:null}{[evidence.date,evidence.expiry_date].filter(value=>value!=null).map((item,index)=><p key={index}>{item.line}</p>)}</details>
 <p>{t('Please review against the original label. This is not professional verification.')}</p></div>;
}
