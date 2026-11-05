// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { LanguageProvider, useLanguage } from './language';
import { api, type PatientPreferences } from '../api/client';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function Probe() {
  const { language, textScale, loadPreferences, savePreferences, preferenceError } = useLanguage();
  return (
    <>
      <output>
        {language}:{textScale}
      </output>
      <button onClick={() => void loadPreferences()}>Read</button>
      <button
        onClick={() => void savePreferences({ preferred_language: 'en', text_scale_percent: 150 })}
      >
        Save
      </button>
      <p role="alert">{preferenceError}</p>
    </>
  );
}

it('uses an explicit preference port without hidden HTTP access and retains saved values on failure', async () => {
  const profile = {
    preferred_language: 'zh',
    text_size: 'standard',
    text_scale_percent: 125,
  } as PatientPreferences;
  const hidden = vi
    .spyOn(api, 'preferences')
    .mockResolvedValue({ preferred_language: 'en' } as PatientPreferences);
  const port = {
    preferences: vi.fn().mockResolvedValue(profile),
    updatePreferences: vi.fn().mockRejectedValue(new Error('offline')),
  };
  render(
    <LanguageProvider port={port}>
      <Probe />
    </LanguageProvider>,
  );
  fireEvent.click(screen.getByText('Read'));
  await waitFor(() => expect(screen.getByText('zh:125')).toBeTruthy());
  expect(hidden).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText('Save'));
  await waitFor(() =>
    expect(port.updatePreferences).toHaveBeenCalledWith({
      preferred_language: 'en',
      text_scale_percent: 150,
    }),
  );
  await waitFor(() => expect(screen.getByText('zh:125')).toBeTruthy());
  expect(screen.getByRole('alert').textContent).toContain('Could not save preferences');
});
