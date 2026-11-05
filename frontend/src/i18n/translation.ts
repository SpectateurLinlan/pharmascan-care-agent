/** Translate existing display keys without reading preferences or doing I/O. */
import type { Language } from './types';
import {
  englishLabels,
  guideEnglishLabels,
  translations,
  galleryTranslations,
  guideTranslations,
} from './messages/catalog';

export function translate(language: Language, text: string): string {
  return language === 'zh'
    ? (guideTranslations[text] ?? galleryTranslations[text] ?? translations[text] ?? text)
    : (guideEnglishLabels[text] ?? englishLabels[text] ?? text);
}
