/** Language and display preferences with explicitly injected persistence. */
import { createContext, useContext, useState, useCallback, useEffect, type ReactNode } from 'react';
import type { PatientPreferences, PreferenceUpdate } from '../shared/contracts/preferences';
import type { PreferencesPort } from './preferencesPort';
import type { Language } from './types';
import { translate } from './translation';

export type { Language } from './types';
const defaults = {
  preferred_language: 'en',
  speech_locale: 'en-SG',
  text_size: 'standard',
  voice_enabled: true,
  tts_autoplay: false,
  reminders_enabled: true,
  reminder_lead_minutes: 0,
  timezone: 'Asia/Singapore',
} as const;

type PlaybackPreferences = {
  ttsProvider: 'browser' | 'tencent';
  speechRate: number;
  setTtsProvider: (provider: 'browser' | 'tencent') => void;
  setSpeechRate: (rate: number) => void;
};

type Profile = Pick<
  PatientPreferences,
  | 'display_name'
  | 'preferred_language'
  | 'speech_locale'
  | 'text_size'
  | 'text_scale_percent'
  | 'voice_enabled'
  | 'tts_autoplay'
  | 'conversation_history_enabled'
  | 'reminder_lead_minutes'
  | 'reminders_enabled'
  | 'timezone'
>;

const Context = createContext<
  PlaybackPreferences & {
    textScale: number;
    previewTextScale: (value: number | null) => void;
    language: Language;
    preferences: Profile;
    setLanguage: (value: Language) => void;
    updatePreferences: (value: PreferenceUpdate) => Promise<void>;
    savePreferences: (value: PreferenceUpdate) => Promise<boolean>;
    loadPreferences: () => Promise<PatientPreferences | undefined>;
    preferenceError: string;
  }
>({
  textScale: 100,
  previewTextScale: () => undefined,
  ttsProvider: 'browser',
  speechRate: 0.9,
  setTtsProvider: () => undefined,
  setSpeechRate: () => undefined,
  language: 'en',
  preferences: defaults,
  setLanguage: () => undefined,
  updatePreferences: async () => undefined,
  savePreferences: async () => false,
  loadPreferences: async () => undefined,
  preferenceError: '',
});

export function LanguageProvider({
  children,
  port,
}: {
  children: ReactNode;
  port: PreferencesPort;
}) {
  const [ttsProvider, setTtsProvider] = useState<'browser' | 'tencent'>('browser');
  const [speechRate, setSpeechRate] = useState(0.9);
  const [preferences, setValue] = useState<Profile>(defaults);
  const [preferenceError, setError] = useState('');
  const [languagePreview, setLanguagePreview] = useState<Language | null>(null);
  const [previewScale, previewTextScale] = useState<number | null>(null);
  const textScale =
    previewScale ??
    preferences.text_scale_percent ??
    (preferences.text_size === 'large' ? 125 : 100);
  useEffect(() => {
    const root = document.documentElement;
    const previous = root.style.getPropertyValue('--font-scale');
    const previousScale = root.getAttribute('data-text-scale');
    root.style.setProperty('--font-scale', String(textScale / 100));
    root.setAttribute('data-text-scale', String(textScale));
    return () => {
      if (previous) root.style.setProperty('--font-scale', previous);
      else root.style.removeProperty('--font-scale');
      if (previousScale === null) root.removeAttribute('data-text-scale');
      else root.setAttribute('data-text-scale', previousScale);
    };
  }, [textScale]);
  const loadPreferences = useCallback(async () => {
    const value = await port.preferences();
    setValue(value);
    setError('');
    return value;
  }, [port]);

  async function savePreferences(value: PreferenceUpdate): Promise<boolean> {
    setError('');
    if (value.preferred_language) setLanguagePreview(value.preferred_language);
    try {
      const saved = await port.updatePreferences(value);
      setValue(saved);
      return true;
    } catch {
      setError('Could not save preferences. Your previous preference is retained.');
      return false;
    } finally {
      if (value.preferred_language) setLanguagePreview(null);
    }
  }

  async function updatePreferences(value: PreferenceUpdate) {
    await savePreferences(value);
  }

  function setLanguage(value: Language) {
    void updatePreferences({ preferred_language: value });
  }

  return (
    <Context.Provider
      value={{
        textScale,
        previewTextScale,
        ttsProvider,
        setTtsProvider,
        speechRate,
        setSpeechRate,
        language: languagePreview ?? preferences.preferred_language,
        preferences,
        setLanguage,
        updatePreferences,
        savePreferences,
        loadPreferences,
        preferenceError,
      }}
    >
      {children}
    </Context.Provider>
  );
}

export function useLanguage() {
  const context = useContext(Context);
  return { ...context, t: (text: string) => translate(context.language, text) };
}
