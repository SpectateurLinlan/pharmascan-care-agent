import type {ReactNode} from 'react';
import type {ReportChallengeResponse} from '../api/client';
import {useLanguage} from '../language';
import {BottomSheet} from './BottomSheet';

/**
 * The single dose-report confirmation sheet.
 *
 * Every screen that lets a patient confirm a self-report renders this, because
 * the confirmation is the safety-critical half of the two-phase contract: the
 * server issues a challenge, the patient sees exactly what will be recorded,
 * and only then is the event written. Three near-identical copies of this
 * existed, which is how safety wording drifts.
 *
 * It presents, and only presents. The caller owns the request.
 */
export function ConfirmReportSheet({summary,title,busy,onConfirm,onCancel,children}:{
  summary: ReportChallengeResponse['summary'];
  title?: string | undefined;
  busy: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  children?: ReactNode | undefined;
}) {
  const {language,t}=useLanguage();
  const status=language==='zh'?t(intakeStatusWords(summary.intake_status)):summary.intake_status_label;
  const safety=language==='zh'?t('A self-report does not prove ingestion.'):summary.safety_notice;
  return <BottomSheet title={t(title??'Confirm your dose report')} busy={busy} onCancel={onCancel}>
    <p className="confirm-what">{summary.medication_display_name}: {summary.dose_amount} {t(summary.dose_unit??'')}</p>
    <p>{summary.local_due_time??t('As needed')}{summary.local_due_time?` (${summary.local_timezone})`:''}</p>
    <p className="confirm-status">{status}</p>
    <p className="notice">{safety}</p>
    <div className="actions">
      <button className="primary" disabled={busy} onClick={onConfirm}>{t('Confirm record')}</button>
      <button disabled={busy} onClick={onCancel}>{t('Cancel')}</button>
    </div>
    {children}
  </BottomSheet>;
}

/** The three self-report outcomes, in the words the patient chose. */
export function intakeStatusWords(intakeStatus: string): string {
  if (intakeStatus === 'reported_taken') return 'Patient reported taken';
  if (intakeStatus === 'reported_not_taken') return 'Patient reported not taken';
  return 'Patient is unsure';
}
