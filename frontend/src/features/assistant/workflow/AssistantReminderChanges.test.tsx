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
const fields = {
  reminders_enabled: false,
  reminder_lead_minutes: 30,
  previous_enabled: true,
  previous_lead_minutes: 0,
  previous_timezone: 'Asia/Singapore',
};
const base: WorkflowView = {
  task_id: 'DEMO-reminder-change',
  revision: 2,
  capability_id: 'reminder.settings',
  state: 'collecting',
  save_mode: 'allowed',
  storage_state: 'saved',
  prompt_key: 'assistant.reminder.collect',
  input_fields: {},
  visible_fields: {
    timezone: 'Asia/Singapore',
    current_settings: { reminders_enabled: true, reminder_lead_minutes: 0 },
  },
  missing_fields: ['reminders_enabled'],
  actions: [],
  explanations: [],
  result_ref: null,
};
const reviewed: WorkflowView = {
  ...base,
  state: 'awaiting_confirmation',
  prompt_key: 'assistant.reminder.patient_review',
  input_fields: fields,
  visible_fields: {
    ...base.visible_fields,
    reminder_review: { payload: { reminders_enabled: false, reminder_lead_minutes: 30 } },
  },
  result_ref: { kind: 'reminder_review', id: 'DEMO-review', version: 1 },
  actions: [
    {
      kind: 'existing_review',
      component_key: 'existing_reminder_review',
      owned_ref: { kind: 'reminder_review', id: 'DEMO-review', version: 1 },
      expected_version: 1,
    },
  ],
};

it('collects settings without native autosave and includes the actual before state', async () => {
  const save = vi.spyOn(api, 'updatePreferences');
  const send = vi.fn().mockResolvedValue({ ...base, revision: 3 });
  render(<AssistantWorkflow view={base} busy={false} onEvent={send} />);
  fireEvent.click(await screen.findByRole('checkbox', { name: 'Medication Reminders' }));
  fireEvent.change(screen.getByLabelText('Reminder Lead Time'), { target: { value: '30' } });
  expect(save).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Apply reminder details' }));
  await waitFor(() =>
    expect(send).toHaveBeenCalledWith(
      expect.objectContaining({ kind: 'provide_fields', values: fields }),
    ),
  );
});

it('prepares a reminder review with reminder copy instead of a medication-plan button', async () => {
  const send = vi.fn();
  render(
    <AssistantWorkflow
      view={{ ...base, state: 'ready_for_review', input_fields: fields, missing_fields: [] }}
      busy={false}
      onEvent={send}
    />,
  );
  fireEvent.click(await screen.findByRole('button', { name: 'Prepare reminder review' }));
  expect(send).toHaveBeenCalledWith(expect.objectContaining({ kind: 'prepare_confirmation' }));
});

it('saves only after independent confirmation with the current binding and checks the actual result', async () => {
  const save = vi.spyOn(api, 'updatePreferences').mockResolvedValue({} as never);
  const send = vi.fn().mockResolvedValue({ ...reviewed, revision: 3, state: 'completed' });
  render(<AssistantWorkflow view={reviewed} busy={false} onEvent={send} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Review reminder change' }));
  expect(save).not.toHaveBeenCalled();
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Cancel' }));
  expect(save).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Review reminder change' }));
  fireEvent.click(
    within(screen.getByRole('dialog')).getByRole('button', { name: 'Confirm reminder change' }),
  );
  await waitFor(() =>
    expect(save).toHaveBeenCalledWith(
      { reminders_enabled: false, reminder_lead_minutes: 30 },
      { task_id: base.task_id, expected_revision: 2 },
    ),
  );
  await waitFor(() =>
    expect(send).toHaveBeenCalledWith(expect.objectContaining({ kind: 'report_business_result' })),
  );
});

it('keeps a failed snooze review and requires result checking instead of resending', async () => {
  const save = vi
    .spyOn(api, 'snoozeReminder')
    .mockRejectedValue(new Error('DEMO response unknown'));
  const task: WorkflowView = {
    ...reviewed,
    capability_id: 'reminder.snooze',
    input_fields: { occurrence_id: 'DEMO-dose', minutes: 15, previous_timezone: 'Asia/Singapore' },
    visible_fields: {
      timezone: 'Asia/Singapore',
      medication_name: 'DEMO medicine',
      due_at: '2099-01-01T00:00:00Z',
      reminder_review: { payload: { occurrence_id: 'DEMO-dose', minutes: 15 } },
    },
  };
  render(<AssistantWorkflow view={task} busy={false} onEvent={vi.fn()} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Review reminder change' }));
  fireEvent.click(
    within(screen.getByRole('dialog')).getByRole('button', { name: 'Confirm reminder change' }),
  );
  expect(await screen.findByRole('alert')).toBeTruthy();
  expect(screen.getByText('DEMO medicine')).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Check reminder result' })).toBeTruthy();
  expect(screen.queryByRole('button', { name: 'Confirm reminder change' })).toBeNull();
  expect(save).toHaveBeenCalledTimes(1);
});

it('offers only explicit existing occurrence choices and retains page-only save boundaries', async () => {
  const send = vi.fn();
  render(
    <AssistantWorkflow
      view={{
        ...base,
        capability_id: 'reminder.snooze',
        save_mode: 'ephemeral',
        storage_state: 'ephemeral',
        actions: [
          {
            kind: 'choice',
            action_id: 'reminder.occurrence',
            options: [
              {
                value: 'DEMO-dose',
                label_key: 'assistant.reminder.select',
                label_text: 'DEMO medicine',
              },
            ],
          },
        ],
      }}
      busy={false}
      onEvent={send}
    />,
  );
  fireEvent.click(await screen.findByRole('button', { name: 'Select: DEMO medicine' }));
  expect(send).toHaveBeenCalledWith(
    expect.objectContaining({
      kind: 'provide_fields',
      values: {
        occurrence_id: 'DEMO-dose',
        previous_remind_at: null,
        previous_timezone: 'Asia/Singapore',
      },
    }),
  );
  expect(screen.queryByRole('button', { name: 'Review reminder change' })).toBeNull();
});
