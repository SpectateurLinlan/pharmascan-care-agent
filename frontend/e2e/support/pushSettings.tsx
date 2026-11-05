// Test-only entry: exercises the actual settings, with I/O supplied by Playwright.
import { useEffect } from 'react';
import { createRoot } from 'react-dom/client';
import { LanguageProvider, useLanguage } from '../../src/app/LanguageProvider';
import { SettingsScreen } from '../../src/features/account/SettingsScreen';
import '../../src/styles/index.css';
function Preview() {
  const { loadPreferences } = useLanguage();
  useEffect(() => {
    void loadPreferences();
  }, [loadPreferences]);
  return (
    <main className="app">
      <p>LOCAL / MOCK — no real notifications</p>
      <SettingsScreen section="reminders" />
    </main>
  );
}
createRoot(document.getElementById('root')!).render(
  <LanguageProvider>
    <Preview />
  </LanguageProvider>,
);
