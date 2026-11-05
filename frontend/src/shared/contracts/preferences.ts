/** Pure backend contract; no transport, browser or UI dependencies. */
export interface PatientPreferences {
  conversation_history_enabled?: boolean;
  display_name?: string | null;
  patient_id: string;
  preferred_language: 'en' | 'zh';
  speech_locale: 'en-SG' | 'zh-CN';
  text_size: 'standard' | 'large';
  text_scale_percent?: number;
  voice_enabled: boolean;
  tts_autoplay: boolean;
  reminder_lead_minutes: number;
  reminders_enabled?: boolean;
  timezone: string;
  created_at: string;
  updated_at: string;
}

export type PreferenceUpdate = Partial<
  Pick<
    PatientPreferences,
    | 'display_name'
    | 'preferred_language'
    | 'text_size'
    | 'text_scale_percent'
    | 'voice_enabled'
    | 'tts_autoplay'
    | 'conversation_history_enabled'
    | 'reminder_lead_minutes'
    | 'reminders_enabled'
    | 'timezone'
  >
>;
