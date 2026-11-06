import { LateDoseFollowUps } from '../care/LateDoseFollowUps';
import { HistoryScreen } from './HistoryScreen';

/** Report eligibility and confirmation stay with care; history remains read-only. */
export function MedicationRecordsScreen({ lateReportsEnabled }: { lateReportsEnabled: boolean }) {
  return (
    <>
      <LateDoseFollowUps enabled={lateReportsEnabled} presentation="disclosure" />
      <HistoryScreen />
    </>
  );
}
