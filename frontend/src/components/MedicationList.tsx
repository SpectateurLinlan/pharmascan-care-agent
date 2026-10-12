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
  return (
    <Card title="My medications" hint="Only active regimens are listed. Previous versions are kept in history.">
      {loading ? <p className="notice">Loading…</p> : null}

      {!loading && medications && medications.medications.length > 0 ? (
        <ul className="med-list">
          {medications.medications.map((medication) => (
            <li className="med" key={medication.medication_id}>
              <span className="med__name">{medication.display_name}</span>
              <span className="med__meta">
                {medication.is_prn ? 'only when needed' : 'scheduled'} · version{' '}
                {medication.version_no}
              </span>
              <span>
                {/* Identity is only ever what a human reviewed; never "verified". */}
                {medication.identity_status === 'user_reviewed_document' ? (
                  <Tag muted>details reviewed by you</Tag>
                ) : (
                  <Tag>identity not reviewed</Tag>
                )}{' '}
                {medication.source_backed ? (
                  <Tag muted>backed by a source record</Tag>
                ) : null}
              </span>
            </li>
          ))}
        </ul>
      ) : null}

      {!loading && medications && medications.medications.length === 0 ? (
        <p className="notice">Nothing here yet. Add a medication to get started.</p>
      ) : null}
    </Card>
  );
}
