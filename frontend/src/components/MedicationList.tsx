import {useLanguage} from '../language';
/** Active medication list, with provenance shown honestly. */

import type { MedicationListResponse } from '../api/client';
import { Card, Tag } from './primitives';

export function MedicationList({
  medications,
  loading,
}: {
  medications: MedicationListResponse | null;
  loading: boolean;
}) {
  const {t}=useLanguage();
  return (
    <Card title="My medications" hint="Only active regimens are listed. Previous versions are kept in history.">
      {loading ? <p className="notice">{t('Loading…')}</p> : null}

      {!loading && medications && medications.medications.length > 0 ? (
        <ul className="med-list">
          {medications.medications.map((medication) => (
            <li className="med" key={medication.medication_id}>
              <span className="med__name">{medication.display_name}</span>
              <span className="med__meta">
                {t(medication.is_prn ? 'only when needed' : 'scheduled')} · {t('version')}{' '}
                {medication.version_no}
              </span>
              <span className="med__meta">{t('Dose amount')}: {medication.dose_amount??t('Not specified')} {t(medication.dose_unit??'')} · {medication.food_instruction?.split('; ').map(value=>t(value)).join('；')??t('Not specified')}</span>
              <span className="med__meta">{t('Course start date')}: {medication.course_start_date ?? t('Not specified')} · {t('Last day (inclusive)')}: {medication.course_end_date ?? t('Not specified')}</span>
              <span>
                {/* Identity is only ever what a human reviewed; never "verified". */}
                {medication.identity_status === 'user_reviewed_document' ? (
                  <Tag muted>{t('details reviewed by you')}</Tag>
                ) : (
                  <Tag>{t('identity not reviewed')}</Tag>
                )}{' '}
                {medication.source_backed ? (
                  <Tag muted>{t('backed by a source record')}</Tag>
                ) : null}
              </span>
            </li>
          ))}
        </ul>
      ) : null}

      {!loading && medications && medications.medications.length === 0 ? (
        <p className="notice">{t('Nothing here yet. Add a medication to get started.')}</p>
      ) : null}
    </Card>
  );
}
