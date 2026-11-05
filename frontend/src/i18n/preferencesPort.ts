/** The app supplies persistence; UI language state never constructs an HTTP client. */
import type { PatientPreferences, PreferenceUpdate } from '../shared/contracts/preferences';

export interface PreferencesPort {
  preferences(): Promise<PatientPreferences>;
  updatePreferences(value: PreferenceUpdate): Promise<PatientPreferences>;
}
