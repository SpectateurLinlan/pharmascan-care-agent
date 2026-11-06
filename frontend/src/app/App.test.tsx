// @vitest-environment jsdom
import { afterEach, beforeEach, it, expect, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { App } from './App';
import { api } from '../api/client';
import { accountAuth } from '../api/auth';
import { StrictMode } from 'react';

vi.mock('../api/client', () => ({
  ApiError: class extends Error {},
  api: {
    reminderAlerts: vi.fn(),
    evidenceTasks: vi.fn(),
    refreshFollowUps: vi.fn(),
    doseFollowUps: vi.fn(),
    health: vi.fn(),
    startDemo: vi.fn(),
    preferences: vi.fn().mockResolvedValue({ preferred_language: 'en' }),
    listMedications: vi.fn(),
    regimenHistory: vi.fn(),
  },
}));
afterEach(() => {
  cleanup();
  localStorage.clear();
  vi.restoreAllMocks();
  vi.resetAllMocks();
});
beforeEach(() => {
  vi.mocked(api.preferences).mockResolvedValue({
    patient_id: 'DEMO-owner',
    preferred_language: 'en',
    timezone: 'Asia/Singapore',
  } as Awaited<ReturnType<typeof api.preferences>>);
  vi.mocked(api.listMedications).mockResolvedValue({
    medications: [],
    item_count: 0,
    note: 'DEMO_ONLY',
  });
  vi.mocked(api.regimenHistory).mockResolvedValue([]);
  vi.mocked(api.evidenceTasks).mockResolvedValue([]);
  vi.mocked(api.reminderAlerts).mockResolvedValue([]);
  for (const owner of ['demo-patient', 'DEMO-owner', 'DEMO-A', 'DEMO-retry'])
    localStorage.setItem(
      `pharmascan.quick-start.v5:${owner}`,
      JSON.stringify({ version: 5, status: 'skipped', step: 0 }),
    );
});
it('shows the home shell immediately while all backend responses remain pending', async () => {
  vi.mocked(api.health).mockReturnValue(new Promise(() => {}));
  render(<App />);
  expect(screen.getByRole('navigation', { name: 'Main navigation' })).toBeTruthy();
  expect(screen.getByRole('heading', { level: 1, name: /MediThread|Today|Welcome/ })).toBeTruthy();
  expect(screen.queryByText('No medication plans have been added.')).toBeNull();
});
it('starts independent record reads while health is pending, without creating a session', async () => {
  vi.mocked(api.health).mockReturnValue(new Promise(() => {}));
  vi.mocked(api.preferences).mockReturnValue(new Promise(() => {}));
  vi.mocked(api.listMedications).mockReturnValue(new Promise(() => {}));
  vi.mocked(api.regimenHistory).mockReturnValue(new Promise(() => {}));
  render(<App />);
  await waitFor(() => expect(api.preferences).toHaveBeenCalledOnce());
  expect(api.listMedications).toHaveBeenCalledOnce();
  expect(api.regimenHistory).toHaveBeenCalledOnce();
  expect(api.startDemo).not.toHaveBeenCalled();
  expect(screen.queryByText('No medication plans have been added.')).toBeNull();
});
it('shows an editable composer before health and session, preserving text when chat becomes ready', async () => {
  let resolveHealth!: (value: Awaited<ReturnType<typeof api.health>>) => void;
  let resolveSession!: (value: Awaited<ReturnType<typeof api.startDemo>>) => void;
  vi.mocked(api.health).mockReturnValue(
    new Promise((resolve) => {
      resolveHealth = resolve;
    }),
  );
  vi.mocked(api.startDemo).mockReturnValue(
    new Promise((resolve) => {
      resolveSession = resolve;
    }),
  );
  vi.mocked(api.preferences).mockResolvedValue({
    patient_id: 'DEMO-owner',
    preferred_language: 'en',
    timezone: 'Asia/Singapore',
  } as Awaited<ReturnType<typeof api.preferences>>);
  vi.mocked(api.listMedications).mockReturnValue(new Promise(() => {}));
  vi.mocked(api.regimenHistory).mockReturnValue(new Promise(() => {}));
  render(<App />);
  const input = screen.getByRole('textbox', { name: 'Review your message before sending' });
  fireEvent.change(input, { target: { value: 'DEMO unsent medicine question' } });
  fireEvent.keyDown(input, { key: 'Enter' });
  expect(screen.getByRole('button', { name: 'Send' })).toHaveProperty('disabled', true);
  expect(api.startDemo).not.toHaveBeenCalled();
  await act(async () => {
    resolveHealth({ status: 'ok', runtime_contract: 'patient-ux-reminders-v1' } as Awaited<
      ReturnType<typeof api.health>
    >);
  });
  await waitFor(() => expect(api.startDemo).toHaveBeenCalledOnce());
  await act(async () => {
    resolveSession({
      patient_id: 'DEMO-owner',
      session_id: 'DEMO-session',
      demo_only: true,
      seeded_medication_count: 0,
      note: 'DEMO_ONLY',
    });
  });
  expect(
    screen.getByRole('textbox', { name: 'Review your message before sending' }),
  ).toHaveProperty('value', 'DEMO unsent medicine question');
  await waitFor(() =>
    expect(screen.getByRole('button', { name: 'Send' })).toHaveProperty('disabled', false),
  );
  expect(screen.queryByText('No medication plans have been added.')).toBeNull();
});
it('shares startup GETs across StrictMode without creating a premature session', async () => {
  vi.mocked(api.health).mockReturnValue(new Promise(() => {}));
  vi.mocked(api.preferences).mockReturnValue(new Promise(() => {}));
  vi.mocked(api.listMedications).mockReturnValue(new Promise(() => {}));
  vi.mocked(api.regimenHistory).mockReturnValue(new Promise(() => {}));
  render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
  await waitFor(() => expect(api.health).toHaveBeenCalledOnce());
  expect(api.preferences).toHaveBeenCalledOnce();
  expect(api.listMedications).toHaveBeenCalledOnce();
  expect(api.regimenHistory).toHaveBeenCalledOnce();
  expect(api.startDemo).not.toHaveBeenCalled();
});
it('retries a failed session without losing or automatically sending the startup draft', async () => {
  vi.mocked(api.health).mockResolvedValue({
    status: 'ok',
    runtime_contract: 'patient-ux-reminders-v1',
  } as Awaited<ReturnType<typeof api.health>>);
  vi.mocked(api.startDemo)
    .mockRejectedValueOnce(new Error('DEMO session unavailable'))
    .mockResolvedValue({
      patient_id: 'DEMO-owner',
      session_id: 'DEMO-session',
      demo_only: true,
      seeded_medication_count: 0,
      note: 'DEMO_ONLY',
    });
  vi.mocked(api.listMedications).mockReturnValue(new Promise(() => {}));
  render(<App />);
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'DEMO retain across retry' } });
  fireEvent.click(await screen.findByRole('button', { name: 'Retry connecting' }));
  await waitFor(() =>
    expect(screen.getByRole('button', { name: 'Send' })).toHaveProperty('disabled', false),
  );
  expect(screen.getByRole('textbox')).toHaveProperty('value', 'DEMO retain across retry');
  expect(api.startDemo).toHaveBeenCalledTimes(2);
});
it('refuses a session from another owner while retaining the local draft', async () => {
  vi.mocked(api.health).mockResolvedValue({
    status: 'ok',
    runtime_contract: 'patient-ux-reminders-v1',
  } as Awaited<ReturnType<typeof api.health>>);
  vi.mocked(api.startDemo).mockResolvedValue({
    patient_id: 'DEMO-other',
    session_id: 'DEMO-wrong-session',
    demo_only: true,
    seeded_medication_count: 0,
    note: 'DEMO_ONLY',
  });
  render(<App />);
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'DEMO local only' } });
  await screen.findByRole('button', { name: 'Retry connecting' });
  expect(screen.getByRole('button', { name: 'Send' })).toHaveProperty('disabled', true);
  expect(screen.getByRole('textbox')).toHaveProperty('value', 'DEMO local only');
  expect(localStorage.getItem('pharmascan.agent-session')).toBeNull();
});
it('clears a recovered startup failure after explicit reconnect', async () => {
  vi.mocked(api.health)
    .mockRejectedValueOnce(new Error('DEMO health offline'))
    .mockResolvedValue({ status: 'ok', runtime_contract: 'patient-ux-reminders-v1' } as Awaited<
      ReturnType<typeof api.health>
    >);
  vi.mocked(api.startDemo).mockResolvedValue({
    patient_id: 'DEMO-owner',
    session_id: 'DEMO-session',
    demo_only: true,
    seeded_medication_count: 0,
    note: 'DEMO_ONLY',
  });
  render(<App />);
  const retry = await screen.findByRole('button', { name: 'Retry connecting' });
  expect(document.querySelector('.app-main')?.getAttribute('data-load-state')).toBe('error');
  fireEvent.click(retry);
  await waitFor(() =>
    expect(document.querySelector('.app-main')?.getAttribute('data-load-state')).toBe('ready'),
  );
  expect(screen.queryByText('DEMO health offline')).toBeNull();
  await waitFor(() => expect(api.reminderAlerts).toHaveBeenCalled());
});
it('keeps a current medication failure visible after reconnecting successfully', async () => {
  vi.mocked(api.health)
    .mockRejectedValueOnce(new Error('DEMO health offline'))
    .mockResolvedValue({ status: 'ok', runtime_contract: 'patient-ux-reminders-v1' } as Awaited<
      ReturnType<typeof api.health>
    >);
  vi.mocked(api.listMedications).mockRejectedValue(new Error('DEMO medications unavailable'));
  vi.mocked(api.startDemo).mockResolvedValue({
    patient_id: 'DEMO-owner',
    session_id: 'DEMO-session',
    demo_only: true,
    seeded_medication_count: 0,
    note: 'DEMO_ONLY',
  });
  render(<App />);
  fireEvent.click(await screen.findByRole('button', { name: 'Retry connecting' }));
  await waitFor(() => expect(api.listMedications).toHaveBeenCalledTimes(2));
  await screen.findByText('DEMO medications unavailable');
  expect(document.querySelector('.app-main')?.getAttribute('data-load-state')).toBe('error');
  expect(screen.queryByText('No medication plans have been added.')).toBeNull();
});
it('does not wait for history to load the core, or claim no registrations while history is unknown', async () => {
  vi.mocked(api.health).mockResolvedValue({
    status: 'ok',
    runtime_contract: 'patient-ux-reminders-v1',
  } as Awaited<ReturnType<typeof api.health>>);
  vi.mocked(api.preferences).mockResolvedValue({
    patient_id: 'DEMO-owner',
    preferred_language: 'en',
    timezone: 'Pacific/Auckland',
  } as Awaited<ReturnType<typeof api.preferences>>);
  vi.mocked(api.listMedications).mockResolvedValue({
    medications: [],
    item_count: 0,
    note: 'DEMO_ONLY',
  });
  vi.mocked(api.startDemo).mockReturnValue(new Promise(() => {}));
  let resolveHistory!: (value: []) => void;
  vi.mocked(api.regimenHistory).mockReturnValue(
    new Promise((resolve) => {
      resolveHistory = resolve;
    }),
  );
  render(<App />);
  await waitFor(() =>
    expect(document.querySelector('.app-main')?.getAttribute('data-load-state')).toBe('ready'),
  );
  expect(screen.queryByText('No medication plans have been added.')).toBeNull();
  await act(async () => {
    resolveHistory([]);
  });
  expect(await screen.findByText('No medication plans have been added.')).toBeTruthy();
});
it('keeps clinical data gated until actual preferences arrive', async () => {
  vi.mocked(api.health).mockResolvedValue({
    status: 'ok',
    runtime_contract: 'patient-ux-reminders-v1',
  } as Awaited<ReturnType<typeof api.health>>);
  vi.mocked(api.listMedications).mockResolvedValue({
    medications: [],
    item_count: 0,
    note: 'DEMO_ONLY',
  });
  vi.mocked(api.regimenHistory).mockResolvedValue([]);
  vi.mocked(api.startDemo).mockReturnValue(new Promise(() => {}));
  let resolvePreferences!: (value: Awaited<ReturnType<typeof api.preferences>>) => void;
  vi.mocked(api.preferences).mockReturnValue(
    new Promise((resolve) => {
      resolvePreferences = resolve;
    }),
  );
  render(<App />);
  await waitFor(() => expect(api.preferences).toHaveBeenCalledOnce());
  expect(screen.getByRole('heading', { name: 'Welcome to MediThread' })).toBeTruthy();
  expect(screen.queryByText('No medication plans have been added.')).toBeNull();
  await act(async () => {
    resolvePreferences({
      patient_id: 'DEMO-A',
      timezone: 'America/New_York',
      preferred_language: 'en',
    } as Awaited<ReturnType<typeof api.preferences>>);
  });
  expect(await screen.findByText('No medication plans have been added.')).toBeTruthy();
});
it('retries a failed preference read before restoring clinical data', async () => {
  vi.mocked(api.health).mockResolvedValue({
    status: 'ok',
    runtime_contract: 'patient-ux-reminders-v1',
  } as Awaited<ReturnType<typeof api.health>>);
  vi.mocked(api.listMedications).mockResolvedValue({
    medications: [],
    item_count: 0,
    note: 'DEMO_ONLY',
  });
  vi.mocked(api.regimenHistory).mockResolvedValue([]);
  vi.mocked(api.startDemo).mockResolvedValue({
    patient_id: 'DEMO-retry',
    session_id: 'DEMO-session',
    demo_only: true,
    seeded_medication_count: 0,
    note: 'DEMO_ONLY',
  });
  localStorage.setItem(
    'pharmascan.quick-start.v5:DEMO-retry',
    JSON.stringify({ version: 5, status: 'skipped', step: 0 }),
  );
  vi.mocked(api.preferences)
    .mockRejectedValueOnce(new Error('DEMO preferences failed'))
    .mockResolvedValue({
      patient_id: 'DEMO-retry',
      timezone: 'America/New_York',
      preferred_language: 'en',
    } as Awaited<ReturnType<typeof api.preferences>>);
  render(<App />);
  await screen.findByText('Your records could not be loaded');
  expect(screen.queryByText('No medication plans have been added.')).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'Retry loading records' }));
  expect(await screen.findByText('No medication plans have been added.')).toBeTruthy();
  expect(api.preferences).toHaveBeenCalledTimes(2);
});
it('retains retry and disables reminder reads when preferences fail before a slower active retry', async () => {
  vi.mocked(api.health).mockResolvedValue({
    status: 'ok',
    runtime_contract: 'patient-ux-reminders-v1',
  } as Awaited<ReturnType<typeof api.health>>);
  vi.mocked(api.listMedications).mockResolvedValue({
    medications: [],
    item_count: 0,
    note: 'DEMO_ONLY',
  });
  vi.mocked(api.regimenHistory).mockResolvedValue([]);
  vi.mocked(api.startDemo).mockResolvedValue({
    patient_id: 'DEMO-retry',
    session_id: 'DEMO-session',
    demo_only: true,
    seeded_medication_count: 0,
    note: 'DEMO_ONLY',
  });
  vi.mocked(api.preferences).mockRejectedValue(new Error('DEMO preferences failed'));
  render(<App />);
  await screen.findByRole('button', { name: 'Retry loading records' });
  let resolveActive!: (value: Awaited<ReturnType<typeof api.listMedications>>) => void;
  vi.mocked(api.listMedications).mockReturnValue(
    new Promise((resolve) => {
      resolveActive = resolve;
    }),
  );
  fireEvent.click(screen.getByRole('button', { name: 'Retry loading records' }));
  await waitFor(() => expect(api.preferences).toHaveBeenCalledTimes(2));
  await act(async () => {
    resolveActive({ medications: [], item_count: 0, note: 'DEMO_ONLY' });
  });
  expect.soft(screen.queryByRole('button', { name: 'Retry loading records' })).not.toBeNull();
  expect(api.reminderAlerts).not.toHaveBeenCalled();
});
it('resolves required onboarding from the preferences owner while Agent setup stays pending', async () => {
  vi.mocked(api.health).mockResolvedValue({
    status: 'ok',
    runtime_contract: 'patient-ux-reminders-v1',
  } as Awaited<ReturnType<typeof api.health>>);
  vi.mocked(api.preferences).mockResolvedValue({
    patient_id: 'DEMO-onboarding',
    preferred_language: 'en',
    timezone: 'Asia/Singapore',
  } as Awaited<ReturnType<typeof api.preferences>>);
  vi.mocked(api.listMedications).mockResolvedValue({
    medications: [],
    item_count: 0,
    note: 'DEMO_ONLY',
  });
  vi.mocked(api.regimenHistory).mockResolvedValue([]);
  vi.mocked(api.startDemo).mockReturnValue(new Promise(() => {}));
  render(<App />);
  await waitFor(() =>
    expect(document.querySelector('.app-main')?.getAttribute('data-load-state')).toBe('ready'),
  );
  expect(document.querySelector('[aria-modal="true"]')).not.toBeNull();
  expect(api.startDemo).toHaveBeenCalledOnce();
});
it('clears the previous owner immediately on an identity change while the new owner loads', async () => {
  let changed: () => void = () => undefined;
  vi.spyOn(accountAuth, 'watchIdentity').mockImplementation((listener) => {
    changed = listener;
    return () => undefined;
  });
  vi.spyOn(accountAuth, 'account').mockResolvedValue({
    kind: 'member',
    email: null,
    verified: true,
  });
  vi.mocked(api.health).mockResolvedValue({
    status: 'ok',
    runtime_contract: 'patient-ux-reminders-v1',
  } as Awaited<ReturnType<typeof api.health>>);
  vi.mocked(api.preferences).mockResolvedValue({
    patient_id: 'DEMO-A',
    display_name: 'DEMO Alice',
    preferred_language: 'en',
    timezone: 'Asia/Singapore',
  } as Awaited<ReturnType<typeof api.preferences>>);
  vi.mocked(api.listMedications).mockResolvedValue({
    medications: [],
    item_count: 0,
    note: 'DEMO_ONLY',
  });
  vi.mocked(api.regimenHistory).mockResolvedValue([]);
  vi.mocked(api.startDemo).mockReturnValue(new Promise(() => {}));
  render(<App />);
  await screen.findByText(/DEMO Alice!/);
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'DEMO previous owner draft' } });
  vi.mocked(api.health).mockReturnValue(new Promise(() => {}));
  await act(async () => {
    changed();
  });
  expect(screen.queryByText(/DEMO Alice/)).toBeNull();
  expect(screen.getByRole('textbox')).toHaveProperty('value', '');
  expect(screen.getByRole('navigation', { name: 'Main navigation' })).toBeTruthy();
});
it('loads essential records alongside session setup and does not wait for session or evidence tasks', async () => {
  vi.mocked(api.health).mockResolvedValue({
    status: 'ok',
    service: 'pharmascan-care-agent',
    database: 'supabase',
    llm: 'unavailable_deterministic_degraded',
    stage2_vision: 'live',
    runtime_contract: 'patient-ux-reminders-v1',
  });
  vi.mocked(api.preferences).mockResolvedValue({
    patient_id: 'demo-patient',
    preferred_language: 'en',
    speech_locale: 'en-SG',
    text_size: 'standard',
    voice_enabled: true,
    tts_autoplay: false,
    reminder_lead_minutes: 0,
    timezone: 'Asia/Singapore',
    created_at: '2026-10-14T00:00:00Z',
    updated_at: '2026-10-14T00:00:00Z',
  });
  let rejectSession!: (reason: Error) => void;
  vi.mocked(api.startDemo).mockReturnValue(
    new Promise((_resolve, reject) => {
      rejectSession = reject;
    }),
  );
  vi.mocked(api.evidenceTasks).mockReturnValue(new Promise(() => {}));
  vi.mocked(api.listMedications).mockResolvedValue({
    item_count: 0,
    medications: [],
    note: 'demo_only',
  });
  vi.mocked(api.regimenHistory).mockResolvedValue([]);
  vi.mocked(api.refreshFollowUps).mockResolvedValue([]);
  render(<App />);
  await waitFor(() =>
    expect(document.querySelector('.app-main')?.getAttribute('data-load-state')).toBe('ready'),
  );
  expect(api.listMedications).toHaveBeenCalledOnce();
  expect(api.preferences).toHaveBeenCalledOnce();
  expect(api.startDemo).toHaveBeenCalledOnce();
  expect(api.evidenceTasks).toHaveBeenCalledOnce();
  expect(screen.queryByText('Your records could not be loaded')).toBeNull();
  await act(async () => {
    rejectSession(new Error('DEMO session unavailable'));
  });
  expect(screen.getByText('Your medication and self-care companion')).toBeTruthy();
  expect(screen.queryByText('Your records could not be loaded')).toBeNull();
});
it('refuses stale backend before session creation or clinical display despite parallel safe reads', async () => {
  vi.mocked(api.health).mockResolvedValue({
    status: 'ok',
    service: 'pharmascan-care-agent',
    database: 'supabase',
    llm: 'unavailable_deterministic_degraded',
    stage2_vision: 'simulated',
  });
  render(<App />);
  await screen.findByText(/app connection needs a restart/);
  expect(api.startDemo).not.toHaveBeenCalled();
  expect(api.listMedications).toHaveBeenCalledOnce();
  expect(screen.queryByText(/No dose due right now/)).toBeNull();
});
it('failed medication read is shown as unavailable instead of zero active medicines', async () => {
  vi.mocked(api.health).mockResolvedValue({
    status: 'ok',
    service: 'pharmascan-care-agent',
    database: 'supabase',
    llm: 'unavailable_deterministic_degraded',
    stage2_vision: 'live',
    runtime_contract: 'patient-ux-reminders-v1',
  });
  vi.mocked(api.preferences).mockResolvedValue({
    patient_id: 'demo-patient',
    preferred_language: 'en',
    speech_locale: 'en-SG',
    text_size: 'standard',
    voice_enabled: true,
    tts_autoplay: false,
    reminder_lead_minutes: 0,
    timezone: 'Asia/Singapore',
    created_at: '2026-10-14T00:00:00Z',
    updated_at: '2026-10-14T00:00:00Z',
  });
  vi.mocked(api.startDemo).mockResolvedValue({
    patient_id: 'demo-patient',
    session_id: 'demo-session',
    demo_only: true,
    seeded_medication_count: 0,
    note: 'demo_only',
  });
  vi.mocked(api.listMedications).mockRejectedValue(new Error('Records unavailable'));
  vi.mocked(api.regimenHistory).mockResolvedValue([]);
  render(<App />);
  await waitFor(() =>
    expect(screen.getByText(/unavailable record is not an empty medication list/)).toBeTruthy(),
  );
  expect(screen.queryByRole('button', { name: 'Compare a pill photo' })).toBeNull();
});

it('unavailable greeting account metadata does not block authenticated business records', async () => {
  vi.mocked(api.refreshFollowUps).mockResolvedValue([]);
  vi.spyOn(accountAuth, 'account').mockRejectedValue(
    new Error('DEMO account metadata unavailable'),
  );
  vi.mocked(api.health).mockResolvedValue({
    status: 'ok',
    service: 'pharmascan-care-agent',
    database: 'supabase',
    llm: 'unavailable_deterministic_degraded',
    stage2_vision: 'live',
    runtime_contract: 'patient-ux-reminders-v1',
  });
  vi.mocked(api.preferences).mockResolvedValue({
    patient_id: 'demo-patient',
    preferred_language: 'en',
    speech_locale: 'en-SG',
    text_size: 'standard',
    voice_enabled: true,
    tts_autoplay: false,
    reminder_lead_minutes: 0,
    timezone: 'Asia/Singapore',
    created_at: '2026-10-14T00:00:00Z',
    updated_at: '2026-10-14T00:00:00Z',
  });
  vi.mocked(api.startDemo).mockResolvedValue({
    patient_id: 'demo-patient',
    session_id: 'demo-session',
    demo_only: true,
    seeded_medication_count: 0,
    note: 'demo_only',
  });
  vi.mocked(api.listMedications).mockResolvedValue({
    item_count: 0,
    medications: [],
    note: 'demo_only',
  });
  vi.mocked(api.regimenHistory).mockResolvedValue([]);
  localStorage.setItem(
    'pharmascan.quick-start.v4:demo-patient',
    JSON.stringify({ version: 4, status: 'skipped', step: 0 }),
  );
  render(<App />);
  await screen.findByText('Your medication and self-care companion');
  expect(await screen.findByText(/Guest!/)).toBeTruthy();
  expect(screen.queryByText('Your records could not be loaded')).toBeNull();
});
