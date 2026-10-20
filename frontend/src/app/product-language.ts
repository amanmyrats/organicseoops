import { environment } from '../environments/environment';

// Bilingual approval is required before draft UI can be exposed in production.
export function draftProductLanguage(preference: unknown): 'en' | 'tr' {
  return !environment.production && preference === 'tr' ? 'tr' : 'en';
}

export function isProductLanguageResult(value: Record<string, unknown>): value is Record<string, unknown> & {
  language: 'en' | 'tr'; current_ui_language: 'en'; current_email_language: 'en' | 'tr';
} {
  return (value['language'] === 'en' || value['language'] === 'tr')
    && value['current_ui_language'] === 'en'
    && (value['current_email_language'] === 'en' || (value['language'] === 'tr' && value['current_email_language'] === 'tr'));
}
