/**
 * Medication enrollment: draft -> review -> explicit confirmation -> active.
 *
 * The UI enforces nothing on its own: every gate (required inputs, source
 * review, single-use confirmation) is enforced by the backend and the UI only
 * reflects what the backend returns. A refusal is always displayed, never
 * swallowed.
 */

import { useState } from 'react';
import {
  api,
  ApiError,
  type ConfirmChallengeResponse,
  type DraftCreateResponse,
  type MedicationListResponse,
} from '../api/client';
import { Card, ErrorNotice, Tag } from './primitives';

type Phase =
  | { kind: 'idle' }
  | { kind: 'drafted'; draft: DraftCreateResponse }
  | { kind: 'reviewed'; draft: DraftCreateResponse }
  | { kind: 'confirming'; draft: DraftCreateResponse; challenge: ConfirmChallengeResponse }
  | { kind: 'activated'; regimenId: string };

export function EnrollScreen({
  sessionId,
  medications,
  onChanged,
}: {
  sessionId: string | null;
  medications: MedicationListResponse | null;
  onChanged: () => void;
}) {
  const [name, setName] = useState('');
  const [doseAmount, setDoseAmount] = useState('');
  const [doseUnit, setDoseUnit] = useState('mg');
  const [time, setTime] = useState('08:00');
  const [isPrn, setIsPrn] = useState(false);
  const [phase, setPhase] = useState<Phase>({ kind: 'idle' });
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

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

  const submitDraft = () =>
    run(async () => {
      const parsedAmount = doseAmount.trim() === '' ? null : Number(doseAmount);
      const draft = await api.createDraft({
        medication_name: name.trim(),
        dose_amount: parsedAmount,
        dose_unit: parsedAmount === null ? null : doseUnit.trim() || null,
        frequency_kind: isPrn ? null : 'daily',
        frequency_local_times: isPrn ? [] : [time],
        is_prn: isPrn,
        food_instruction: isPrn ? 'as needed' : null,
      });
      setPhase({ kind: 'drafted', draft });
    });

  const submitReview = (draft: DraftCreateResponse) =>
    run(async () => {
      await api.reviewDraft(draft.source_id);
      setPhase({ kind: 'reviewed', draft });
    });

  const requestConfirmation = (draft: DraftCreateResponse) =>
    run(async () => {
      if (!sessionId) {
        throw new Error('No agent session yet — start the demo session first.');
      }
      const challenge = await api.requestChallenge(draft.regimen_id, sessionId);
      setPhase({ kind: 'confirming', draft, challenge });
    });

  const confirmActivation = (draft: DraftCreateResponse, challenge: ConfirmChallengeResponse) =>
    run(async () => {
      const activated = await api.activate({
        regimen_id: draft.regimen_id,
        challenge_id: challenge.challenge_id,
        session_id: challenge.session_id,
        session_state: challenge.session_state,
        session_state_version: challenge.session_state_version,
      });
      setPhase({ kind: 'activated', regimenId: activated.regimen_id });
      setName('');
      setDoseAmount('');
      onChanged();
    });

  const reset = () => {
    setPhase({ kind: 'idle' });
    setError(null);
  };

  return (
    <Card
      title="Add a medication"
      hint="A draft is never active on its own. You review the details, then explicitly confirm."
    >
      {phase.kind === 'idle' || phase.kind === 'activated' ? (
        <>
          {phase.kind === 'activated' ? (
            <div className="status status--ok" role="status">
              Regimen activated. It now appears in your medication list.
            </div>
          ) : null}

          <div className="field">
            <label htmlFor="med-name">Medication name</label>
            <input
              id="med-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="e.g. Amlodipine"
              autoComplete="off"
            />
          </div>

          <div className="grid-2">
            <div className="field">
              <label htmlFor="med-dose">Dose amount</label>
              <input
                id="med-dose"
                value={doseAmount}
                onChange={(event) => setDoseAmount(event.target.value)}
                inputMode="decimal"
                placeholder="e.g. 5"
              />
            </div>
            <div className="field">
              <label htmlFor="med-unit">Unit</label>
              <input
                id="med-unit"
                value={doseUnit}
                onChange={(event) => setDoseUnit(event.target.value)}
                placeholder="mg"
              />
            </div>
          </div>

          <div className="field">
            <label htmlFor="med-time">Time of day</label>
            <input
              id="med-time"
              type="time"
              value={time}
              onChange={(event) => setTime(event.target.value)}
              disabled={isPrn}
            />
          </div>

          <div className="field">
            <label htmlFor="med-prn">
              <input
                id="med-prn"
                type="checkbox"
                checked={isPrn}
                onChange={(event) => setIsPrn(event.target.checked)}
                style={{ width: 'auto', minHeight: 'auto', marginRight: '0.5rem' }}
              />
              Take only when needed (no fixed schedule)
            </label>
          </div>

          <div className="actions">
            <button
              className="primary"
              onClick={submitDraft}
              disabled={busy || name.trim() === ''}
            >
              Create draft
            </button>
            {phase.kind === 'activated' ? (
              <button onClick={reset} disabled={busy}>
                Add another
              </button>
            ) : null}
          </div>
        </>
      ) : null}

      {phase.kind === 'drafted' ? (
        <>
          <div className="status status--warn" role="status">
            Draft saved — not active yet.
            {phase.draft.missing_instructions.length > 0 ? (
              <>
                {' '}
                Still needed: <strong>{phase.draft.missing_instructions.join(', ')}</strong>.
                Activating will be refused until these are provided.
              </>
            ) : null}
          </div>
          <p className="notice">
            Next: confirm the extracted details are correct. This is what marks the
            medication-name evidence as reviewed by you.
          </p>
          <div className="actions">
            <button className="primary" onClick={() => submitReview(phase.draft)} disabled={busy}>
              I have reviewed these details
            </button>
            <button onClick={reset} disabled={busy}>
              Cancel
            </button>
          </div>
        </>
      ) : null}

      {phase.kind === 'reviewed' ? (
        <>
          <div className="status status--ok" role="status">
            Details marked as reviewed by you. The regimen is still not active.
          </div>
          <div className="actions">
            <button
              className="primary"
              onClick={() => requestConfirmation(phase.draft)}
              disabled={busy}
            >
              Show me the summary to confirm
            </button>
            <button onClick={reset} disabled={busy}>
              Cancel
            </button>
          </div>
        </>
      ) : null}

      {phase.kind === 'confirming' ? (
        <>
          <div className="status status--warn" role="status">
            <strong>Please check this before I save it.</strong>
            <ul style={{ margin: '0.4rem 0 0', paddingLeft: '1.2rem' }}>
              <li>Medication: {phase.challenge.summary.medication_name}</li>
              <li>
                Dose: {phase.challenge.summary.dose_amount ?? '—'}{' '}
                {phase.challenge.summary.dose_unit ?? ''}
              </li>
              <li>
                Schedule:{' '}
                {phase.challenge.summary.is_prn
                  ? 'only when needed'
                  : (phase.challenge.summary.frequency?.local_times.join(', ') ??
                    'not specified')}
              </li>
              <li>Your local time zone: {phase.challenge.summary.local_timezone}</li>
            </ul>
            <span className="status__code">
              summary version {phase.challenge.session_state_version} · expires{' '}
              {new Date(phase.challenge.expires_at).toLocaleTimeString()}
            </span>
          </div>
          <div className="actions">
            <button
              className="primary"
              onClick={() => confirmActivation(phase.draft, phase.challenge)}
              disabled={busy}
            >
              Yes, save this medication
            </button>
            <button onClick={reset} disabled={busy}>
              No, go back
            </button>
          </div>
        </>
      ) : null}

      {error ? <ErrorNotice error={error} /> : null}

      {medications && medications.item_count > 0 ? (
        <p className="notice">
          {medications.item_count} active medication
          {medications.item_count === 1 ? '' : 's'} currently on your list.
        </p>
      ) : (
        <p className="notice">
          No active medication yet <Tag muted>nothing activated</Tag>
        </p>
      )}
    </Card>
  );
}

export function isAlreadyRecordedError(error: unknown): boolean {
  return error instanceof ApiError && error.code === 'DUPLICATE_EVENT';
}
