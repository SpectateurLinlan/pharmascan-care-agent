import {useEffect,useState} from 'react';
import {api,type DoseHistoryEntry,type RegimenHistoryItem} from '../api/client';
import type {Barrier,BarrierKind,StockStatus} from '../api/care';
import {useLanguage} from '../language';
import {Callout,StatusPill} from '../ui/primitives';

/**
 * Medication difficulties, derived rather than asked.
 *
 * The screen used to be a blank form: the patient had to name their own
 * difficulty and pick a category from a list. The records the app already holds
 * answer part of that question, so this panel states what those records show and
 * offers a next step.
 *
 * Three tiers, deliberately never mixed:
 *
 *   From your records   a count taken from stored data. Arithmetic only.
 *   Suggested next step a proposal the patient may accept or ignore. It is only
 *                       ever raised when the patient's *own* recorded words are
 *                       the evidence for it.
 *   You told us         a patient-confirmed fact, saved through the existing
 *                       review-and-confirm flow.
 *
 * Two things this must never do, because they are clinical-safety boundaries:
 *
 *   1. a scheduled dose with no self-report is never counted, worded or implied
 *      as a missed dose — a missing report is missing information;
 *   2. a barrier is never inferred from supply or from a trend. Low stock is
 *      reported as a fact about stock and carries no suggested category.
 */

export type ObservationKind = 'no_report' | 'reported_not_taken' | 'unsure_reports' | 'low_supply';

export interface DerivedObservation {
  kind: ObservationKind;
  /** The stored numbers the sentence is built from. Shown to the patient. */
  count: number;
  days: number;
  /**
   * Only set when the patient's own recorded report is the evidence for that
   * category. `null` means "no category may be inferred" — the patient may still
   * add a note of their own.
   */
  suggestedCategory: BarrierKind | null;
}

/**
 * Pure derivation. Every branch is arithmetic over stored records; nothing is
 * estimated and no category is guessed from a count.
 */
export function deriveObservations(
  history: DoseHistoryEntry[] | null,
  stock: StockStatus | null,
  days: number,
): DerivedObservation[] {
  const rows: DerivedObservation[] = [];
  if (history) {
    const withoutReport = history.filter(entry => !entry.reported).length;
    const notTaken = history.filter(entry => entry.intake_status === 'reported_not_taken').length;
    const unsure = history.filter(entry => entry.intake_status === 'unsure').length;
    if (withoutReport > 0) rows.push({kind: 'no_report', count: withoutReport, days, suggestedCategory: null});
    if (notTaken > 0) rows.push({kind: 'reported_not_taken', count: notTaken, days, suggestedCategory: null});
    // The patient recorded "Unsure" themselves. That is their own statement, so
    // it — and only it — can carry a suggested category.
    if (unsure > 0) rows.push({kind: 'unsure_reports', count: unsure, days, suggestedCategory: 'unsure_taken'});
  }
  if (stock?.low_stock) {
    rows.push({kind: 'low_supply', count: stock.estimated_days ?? 0, days, suggestedCategory: null});
  }
  return rows;
}

export function MedicationDifficultiesPanel({regimens,barriers,onAddNote}:{
  regimens: RegimenHistoryItem[];
  barriers: Barrier[];
  /** Opens the existing manual form, optionally pre-filled with a note. */
  onAddNote: (suggestion: {description: string; category: BarrierKind | null}) => void;
}) {
  const {t}=useLanguage();
  const [history,setHistory]=useState<DoseHistoryEntry[]|null>(null);
  const [stock,setStock]=useState<StockStatus|null>(null);
  const [dismissed,setDismissed]=useState<string[]>([]);

  const first=regimens[0]??null;
  useEffect(()=>{
    if(!first){setHistory(null);setStock(null);return;}
    let live=true;
    void api.doseHistory(first.regimen_id,7).then(value=>{if(live)setHistory(value.entries);}).catch(()=>{if(live)setHistory(null);});
    void api.inventory(first.medication_id).then(value=>{if(live)setStock(value);}).catch(()=>{if(live)setStock(null);});
    return()=>{live=false;};
  },[first?.regimen_id,first?.medication_id]);

  const observations=deriveObservations(history,stock,7);

  const sentence=(row:DerivedObservation)=>{
    if(row.kind==='no_report') return t('{count} scheduled doses in the last {days} days have no report from you. A missing report is not a missed dose.').replace('{count}',String(row.count)).replace('{days}',String(row.days));
    if(row.kind==='reported_not_taken') return t('You reported not taking {count} doses in the last {days} days.').replace('{count}',String(row.count)).replace('{days}',String(row.days));
    if(row.kind==='unsure_reports') return t('You marked {count} doses as unsure whether you took them.').replace('{count}',String(row.count));
    return t('Your recorded supply is low — about {count} days left at the recorded plan.').replace('{count}',String(row.count));
  };

  const suggestions=observations.filter(row=>row.suggestedCategory&&!dismissed.includes(row.kind));

  return <div className="difficulties-panel">
    <section className="observation-group">
      <h3 className="observation-group__title">{t('From your records')}</h3>
      <p className="observation-group__note">{t('These are counts from what you have already recorded. They are not a judgement about your medication use.')}</p>
      {observations.length?<ul className="observation-list">{observations.map(row=><li key={row.kind}>
        <p className="observation-list__text">{sentence(row)}</p>
        <p className="observation-list__source">{t('Observation from your records, not a diagnosis.')}</p>
      </li>)}</ul>:<p className="observation-group__note">{t('Nothing to show from your records yet.')}</p>}
    </section>

    {suggestions.length?<section className="observation-group">
      <h3 className="observation-group__title">{t('Suggested next step')}</h3>
      {suggestions.map(row=><Callout key={row.kind} tone="info" icon="info" title={row.suggestedCategory==='unsure_taken'?'Check your reported history':'Consider a next step'}>
        <p>{t(row.suggestedCategory==='unsure_taken'?'You can check your own reports instead of taking an extra dose.':'You can record what made this difficult and choose a support action.')}</p>
        <div className="actions">
          <button type="button" onClick={()=>onAddNote({description:'',category:row.suggestedCategory})}>{t('This matches me — record it')}</button>
          <button type="button" onClick={()=>setDismissed(previous=>[...previous,row.kind])}>{t('Not for me')}</button>
        </div>
      </Callout>)}
      <p className="observation-group__note">{t('A suggestion is not a finding. You can ignore it, and you can record something different.')}</p>
    </section>:null}

    <section className="observation-group">
      <h3 className="observation-group__title">{t('You told us')}</h3>
      {barriers.length?<ul className="observation-list">{barriers.map(row=><li key={row.id}>
        <p className="observation-list__text"><StatusPill tone="quiet" label="Confirmed by you"/> {t(row.category)}{row.description?` — ${row.description}`:''}</p>
      </li>)}</ul>:<p className="observation-group__note">{t('You have not recorded a difficulty yet.')}</p>}
      <button type="button" onClick={()=>onAddNote({description:'',category:null})}>{t('Add a note in my own words')}</button>
    </section>
  </div>;
}
