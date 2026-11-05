// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { api } from '../../../api/client';
import type { WorkflowView } from '../../../api/assistantWorkflows';
import { AssistantWorkflow } from './AssistantWorkflow';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
const prefs = {
  display_name: null,
  preferred_language: 'en',
  speech_locale: 'en-SG',
  text_size: 'standard',
  text_scale_percent: 100,
  voice_enabled: true,
  tts_autoplay: false,
  conversation_history_enabled: false,
  reminders_enabled: true,
  reminder_lead_minutes: 0,
  timezone: 'Asia/Singapore',
};
const base: WorkflowView = {
  task_id: 'DEMO-setting',
  revision: 1,
  capability_id: 'preference.text',
  state: 'collecting',
  save_mode: 'allowed',
  storage_state: 'saved',
  prompt_key: 'assistant.settings.collect',
  input_fields: {},
  visible_fields: { current_preferences: prefs },
  missing_fields: ['change'],
  actions: [],
  explanations: [],
  result_ref: null,
};
const reviewed: WorkflowView = {
  ...base,
  revision: 2,
  state: 'awaiting_confirmation',
  prompt_key: 'assistant.settings.patient_review',
  input_fields: { text_scale_percent: 125, previous: prefs },
  visible_fields: {
    current_preferences: prefs,
    settings_review: { target_id: null, payload: { text_scale_percent: 125 } },
  },
  actions: [
    {
      kind: 'existing_review',
      component_key: 'existing_preference_review',
      owned_ref: { kind: 'settings_review', id: 'DEMO-review', version: 1 },
      expected_version: 1,
    },
  ],
  result_ref: { kind: 'settings_review', id: 'DEMO-review', version: 1 },
};
it('collects text preferences with a native typed previous snapshot without autosave', async () => {
  const save = vi.spyOn(api, 'updatePreferences');
  const send = vi.fn().mockResolvedValue({ ...base, revision: 2 });
  render(<AssistantWorkflow view={base} busy={false} onEvent={send} />);
  fireEvent.change(await screen.findByLabelText('Text size'), { target: { value: '125' } });
  expect(save).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Apply settings details' }));
  await waitFor(() =>
    expect(send).toHaveBeenCalledWith(
      expect.objectContaining({
        kind: 'provide_fields',
        values: { text_scale_percent: 125, previous: prefs },
      }),
    ),
  );
});
it('only saves after the independent sheet confirmation and checks the actual native result', async () => {
  const save = vi.spyOn(api, 'updatePreferences').mockResolvedValue({} as never);
  const send = vi.fn().mockResolvedValue({ ...reviewed, revision: 3, state: 'completed' });
  render(<AssistantWorkflow view={reviewed} busy={false} onEvent={send} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Review settings change' }));
  expect(save).not.toHaveBeenCalled();
  fireEvent.click(
    within(screen.getByRole('dialog')).getByRole('button', { name: 'Confirm settings change' }),
  );
  await waitFor(() =>
    expect(save).toHaveBeenCalledWith(
      { text_scale_percent: 125 },
      { task_id: base.task_id, expected_revision: 2 },
    ),
  );
  await waitFor(() =>
    expect(send).toHaveBeenCalledWith(expect.objectContaining({ kind: 'report_business_result' })),
  );
});
it('keeps contact details page-only until explicit storage consent and then submits typed draft fields', async () => {
  const send = vi.fn().mockResolvedValue({ ...base, revision: 2 });
  const save = vi.spyOn(api, 'createCaregiver');
  render(
    <AssistantWorkflow
      view={{ ...base, capability_id: 'caregiver.add', visible_fields: {} }}
      busy={false}
      onEvent={send}
    />,
  );
  fireEvent.change(await screen.findByLabelText('Contact name'), {
    target: { value: 'DEMO contact' },
  });
  fireEvent.change(screen.getByLabelText('Email address'), {
    target: { value: 'demo.contact@example.invalid' },
  });
  expect(screen.getByRole('button', { name: 'Apply settings details' })).toHaveProperty(
    'disabled',
    true,
  );
  expect(send).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('checkbox'));
  fireEvent.click(screen.getByRole('button', { name: 'Apply settings details' }));
  await waitFor(() =>
    expect(send).toHaveBeenCalledWith(
      expect.objectContaining({
        values: {
          name: 'DEMO contact',
          relationship: null,
          contact_type: 'email',
          contact_value: 'demo.contact@example.invalid',
          storage_consent: true,
        },
      }),
    ),
  );
  expect(save).not.toHaveBeenCalled();
});
it('retains a failed native review and requires result checking instead of silently resending', async () => {
  vi.spyOn(api, 'updatePreferences').mockRejectedValue(new Error('DEMO unknown'));
  render(<AssistantWorkflow view={reviewed} busy={false} onEvent={vi.fn()} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Review settings change' }));
  fireEvent.click(
    within(screen.getByRole('dialog')).getByRole('button', { name: 'Confirm settings change' }),
  );
  expect(await screen.findByRole('alert')).toBeTruthy();
  expect(screen.queryByRole('button', { name: 'Confirm settings change' })).toBeNull();
  expect(screen.getByRole('button', { name: 'Check settings result' })).toBeTruthy();
});
it('describes a no-save settings draft without medication-plan wording', async () => {
  render(
    <AssistantWorkflow
      view={{ ...base, save_mode: 'ephemeral', storage_state: 'ephemeral' }}
      busy={false}
      onEvent={vi.fn()}
    />,
  );
  expect(
    await screen.findByText(
      'Saving keeps this settings draft. The change still needs separate review and confirmation.',
    ),
  ).toBeTruthy();
  expect(screen.queryByText(/The plan still needs review/)).toBeNull();
});
