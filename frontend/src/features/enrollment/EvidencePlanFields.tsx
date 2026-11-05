import type { EvidenceProduct, EvidenceTask, GalleryEntry } from '../../api/client';
import { useLanguage } from '../../i18n/language';
import { MedicationDate, MedicationTimes } from './MedicationInputs';

export interface SourcePlanValues {
  amount: string;
  unit: string;
  times: string;
  food: string;
  start: string;
  end: string;
  prn: boolean;
  category: EvidenceProduct['category'];
  patientEdited: boolean;
  reviewed: boolean;
}

/** Shared controlled fields. No storage, patient API calls or activation authority. */
export function EvidencePlanFields({
  task,
  value,
  onChange,
  onPrepare,
  busy = false,
  products = [],
  onLink,
  submitLabel,
}: {
  task: EvidenceTask;
  value: SourcePlanValues;
  onChange: (patch: Partial<SourcePlanValues>) => void;
  onPrepare: () => void;
  busy?: boolean;
  products?: GalleryEntry[];
  onLink?: (medicationId: string) => void;
  submitLabel?: string;
}) {
  const { t } = useLanguage();
  const interval =
    task.suggested_regimen?.frequency_rule?.kind === 'interval'
      ? task.suggested_regimen.frequency_rule
      : null;
  const edited = (patch: Partial<SourcePlanValues>) => onChange({ ...patch, patientEdited: true });
  return (
    <div className="evidence-review">
      <label className="field">
        {t('Product category from your records')}
        <select
          disabled={busy}
          value={value.category}
          onChange={(event) =>
            onChange({ category: event.target.value as EvidenceProduct['category'] })
          }
        >
          <option value="unknown">{t('Not specified')}</option>
          <option value="POM">POM</option>
          <option value="P">P</option>
          <option value="GSL">GSL</option>
          <option value="supplement">{t('Health supplement')}</option>
        </select>
      </label>
      <label className="field">
        {t('Dose amount')}
        <input
          disabled={busy}
          type="number"
          min="0.01"
          step="any"
          value={value.amount}
          onChange={(event) => edited({ amount: event.target.value })}
        />
      </label>
      <label className="field">
        {t('Unit')}
        <input
          disabled={busy}
          value={value.unit}
          onChange={(event) => edited({ unit: event.target.value })}
        />
      </label>
      <fieldset disabled={busy}>
        {!value.prn ? (
          interval ? (
            <>
              <p>
                {t('Every N hours')}: {interval.every_hours}
              </p>
              <MedicationDate
                type="time"
                label="First dose time (optional)"
                value={value.times}
                onChange={(times) => edited({ times })}
              />
              <p className="notice">
                {t(
                  'When is the first dose? If left blank, 08:00 is used by default. The course start date is the first-dose date. Check both before confirming; this is not a report that you took it.',
                )}
              </p>
            </>
          ) : (
            <MedicationTimes value={value.times} onChange={(times) => edited({ times })} />
          )
        ) : null}
        <label className="consent">
          <input
            type="checkbox"
            checked={value.prn}
            onChange={(event) => edited({ prn: event.target.checked })}
          />
          {t('Take only when needed (no fixed schedule)')}
        </label>
        <label className="field">
          {t('Food or PRN instructions')}
          <input value={value.food} onChange={(event) => edited({ food: event.target.value })} />
        </label>
        <MedicationDate
          label="Course start date"
          value={value.start}
          onChange={(start) => edited({ start })}
        />
        <MedicationDate
          label="Course end date"
          value={value.end}
          onChange={(end) => edited({ end })}
        />
      </fieldset>
      {task.possible_duplicate_ids.length ? (
        <div>
          <p>
            {t(
              'A similar medicine is already saved. Link the photo to that medicine or add evidence that identifies a different product.',
            )}
          </p>
          {onLink
            ? products
                .filter((row) => task.possible_duplicate_ids.includes(row.medication.id))
                .map((row) => (
                  <button
                    disabled={busy}
                    key={row.medication.id}
                    onClick={() => onLink(row.medication.id)}
                  >
                    {t('Link to existing medicine')}: {row.medication.display_name}
                  </button>
                ))
            : null}
        </div>
      ) : null}
      <label className="consent">
        <input
          disabled={busy}
          type="checkbox"
          checked={value.reviewed}
          onChange={(event) => onChange({ reviewed: event.target.checked })}
        />
        {t('I reviewed these details against my medication instructions.')}
      </label>
      <button
        className="primary"
        disabled={
          busy ||
          !!task.conflicts.length ||
          !value.reviewed ||
          !value.amount ||
          (!value.prn && (interval ? !value.start : !value.times.trim()))
        }
        onClick={onPrepare}
      >
        {submitLabel ?? t('Prepare activation confirmation')}
      </button>
    </div>
  );
}
