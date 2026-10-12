/**
 * Today screen: the currently due dose and the four patient choices
 * [Taken] [Check pill] [Not now] [Unsure].
 *
 * "Check pill" is explicitly NOT implemented in this build: there is no camera
 * pipeline and no live Stage2 vision provider (B01). The button is present but
 * disabled and labelled as unavailable — it must never pretend to have run a
 * visual match.
 */

import { useEffect, useState } from 'react';
import {
  api,
  type DoseHistoryResponse,
  type DueDoseResponse,
  type MedicationSummary,
} from '../api/client';
import { Card, ErrorNotice, Tag } from './primitives';

const CHOICES: { label: string; value: string }[] = [
  { label: 'Taken', value: 'Taken' },
  { label: 'Not now', value: 'Not now' },
  { label: 'Unsure', value: 'Unsure' },
];

export function TodayScreen({
  medications,
  onChanged,
}: {
  medications: MedicationSummary[];
  onChanged: () => void;
}) {
  const [selected, setSelected] = useState<MedicationSummary | null>(null);
  const [due, setDue] = useState<DueDoseResponse | null>(null);
  const [history, setHistory] = useState<DoseHistoryResponse | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [lastResult, setLastResult] = useState<string | null>(null);

  useEffect(() => {
    if (medications.length > 0 && selected === null) {
      setSelected(medications[0] ?? null);
    }
  }, [medications, selected]);

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (caught) {
      setError(caught);
    } finally {
      setBusy(false);
    }
  }

  const loadFor = (medication: MedicationSummary) =>
    run(async () => {
      setSelected(medication);
      setLastResult(null);
      const dueDose = await api.dueDose(medication.regimen_id);
      setDue(dueDose);
      setHistory(await api.doseHistory(medication.regimen_id));
    });

  const report = (choice: string) =>
    run(async () => {
      if (!due?.occurrence_id) {
        throw new Error('No dose is currently due for this medication.');
      }
      const result = await api.report(due.occurrence_id, {
        regimen_id: due.regimen_id,
        intake_status: choice,
        // One key per occurrence+choice: a retry is idempotent, a genuine
        // second report on the same occurrence is prevented by the backend.
        idempotency_key: `${due.occurrence_id}:${choice}`,
      });
      setLastResult(
        result.already_recorded
          ? `Already recorded as "${result.intake_status}" — nothing changed.`
          : `Recorded as "${result.intake_status}".`,
      );
      onChanged();
      if (selected) {
        setHistory(await api.doseHistory(selected.regimen_id));
      }
    });

  if (medications.length === 0) {
    return (
      <Card title="Today">
        <p className="notice">
          No active medication yet, so there is no dose to check.
        </p>
      </Card>
    );
  }

  return (
    <Card
      title="Today"
      hint="This records what you tell me. It is not proof that a medicine was swallowed."
    >
      <div className="field">
        <label htmlFor="today-med">Medication</label>
        <select
          id="today-med"
          value={selected?.medication_id ?? ''}
          onChange={(event) => {
            const found = medications.find(
              (m) => m.medication_id === event.target.value,
            );
            if (found) void loadFor(found);
          }}
        >
          {medications.map((medication) => (
            <option key={medication.medication_id} value={medication.medication_id}>
              {medication.display_name}
            </option>
          ))}
        </select>
      </div>

      {due === null && selected !== null ? (
        <div className="actions">
          <button className="primary" onClick={() => void loadFor(selected)} disabled={busy}>
            Check what is due now
          </button>
        </div>
      ) : null}

      {due ? (
        due.occurrence_id ? (
          <>
            <div className="status status--warn" role="status">
              <strong>{due.medication_display_name}</strong> is due
              {due.dose_description ? ` — ${due.dose_description}` : ''}.
              {due.due_at ? (
                <span className="status__code">
                  due {new Date(due.due_at).toLocaleString()}
                </span>
              ) : null}
            </div>

            <div className="actions">
              {CHOICES.map((choice) => (
                <button
                  key={choice.value}
                  className="choice primary"
                  onClick={() => report(choice.value)}
                  disabled={busy}
                >
                  {choice.label}
                </button>
              ))}
              <button
                className="choice"
                disabled
                title="No camera pipeline and no live vision provider in this build"
              >
                Check pill <Tag muted>unavailable</Tag>
              </button>
            </div>

            <p className="notice">
              <Tag muted>visual check not run</Tag> No photo was taken. Any photo
              comparison is advisory evidence only and would never prove identity.
            </p>
          </>
        ) : (
          <div className="status status--ok" role="status">
            {due.is_prn
              ? 'This medication is taken only when needed, so nothing is scheduled.'
              : 'Nothing is due right now for this medication.'}
          </div>
        )
      ) : null}

      {lastResult ? (
        <div className="status status--ok" role="status">
          {lastResult} A self report never proves ingestion.
        </div>
      ) : null}

      {error ? <ErrorNotice error={error} /> : null}

      {history ? (
        <details>
          <summary>Recent history ({history.item_count} entries)</summary>
          <p className="notice">{history.note}</p>
          <ul className="history">
            {history.entries.map((entry, index) => (
              <li key={`${entry.occurrence_id ?? 'x'}-${index}`}>
                <span>
                  {entry.due_at ? new Date(entry.due_at).toLocaleString() : 'no scheduled time'}
                </span>
                <span>
                  {entry.reported ? (
                    entry.intake_status
                  ) : (
                    <>
                      not reported <Tag muted>not a missed dose</Tag>
                    </>
                  )}
                </span>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </Card>
  );
}
