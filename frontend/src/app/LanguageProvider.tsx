/** Composition adapter: connect UI preference state to the authorized backend facade. */
import type { ReactNode } from 'react';
import { api } from '../api/client';
import { LanguageProvider as PreferenceProvider } from '../i18n/language';

export { useLanguage } from '../i18n/language';
export type { Language } from '../i18n/language';
export function LanguageProvider({ children }: { children: ReactNode }) {
  return <PreferenceProvider port={api}>{children}</PreferenceProvider>;
}
