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
const base: WorkflowView = {
  task_id: 'DEMO-exact-review',
  revision: 2,
  capability_id: 'followup.edit',
  state: 'awaiting_confirmation',
  save_mode: 'allowed',
  storage_state: 'saved',
  prompt_key: 'assistant.care.patient_review',
  visible_fields: {},
  missing_fields: [],
  actions: [],
  explanations: [],
  result_ref: { kind: 'care_review', id: 'DEMO-review', version: 1 },
};
it('shows changed followup title type and removed association before exact patient confirmation', async () => {
  const payload = {
    id: 'DEMO-review',
    expected_version: 1,
    status: 'open',
    due_at: null,
    notes: 'DEMO note',
    confirmed: false,
    title: 'DEMO NEW proposed title',
    category: 'monitoring',
    medication_id: null,
    regimen_id: null,
  };
  const write = vi.spyOn(api, 'updateCareTask').mockResolvedValue({} as never);
  const event = vi.fn().mockResolvedValue({ ...base, revision: 3, state: 'completed' });
  render(
    <AssistantWorkflow
      view={{
        ...base,
        visible_fields: {
          target_name: 'DEMO OLD title',
          association_state: 'removed',
          care_review: { target_id: 'DEMO-target', payload },
          proposal: { action: 'task_update', task_id: 'DEMO-target', task_update: payload },
        },
      }}
      busy={false}
      onEvent={event}
    />,
  );
  fireEvent.click(await screen.findByRole('button', { name: 'Review care record' }));
  const dialog = screen.getByRole('dialog');
  expect(dialog.textContent).toContain('DEMO NEW proposed title');
  expect(dialog.textContent).toContain('monitoring');
  expect(dialog.textContent).toContain('Remove the medication and plan link');
  expect(write).not.toHaveBeenCalled();
  fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }));
  expect(write).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Review care record' }));
  fireEvent.click(screen.getByRole('button', { name: 'Confirm record' }));
  await waitFor(() =>
    expect(write).toHaveBeenCalledWith(
      'DEMO-target',
      { ...payload, confirmed: true },
      { task_id: base.task_id, expected_revision: 2 },
    ),
  );
});
it('shows a readable proposed medication association when creating a followup', async () => {
  const payload = {
    id: 'DEMO-review',
    title: 'DEMO linked task',
    category: 'monitoring',
    due_at: '2099-10-28T12:00:00Z',
    notes: '',
    confirmed: false,
    medication_id: 'DEMO-med',
    regimen_id: 'DEMO-plan',
    reminder_minutes: null,
  };
  const write = vi.spyOn(api, 'createCareTask');
  render(
    <AssistantWorkflow
      view={{
        ...base,
        capability_id: 'followup.add',
        visible_fields: {
          association_state: 'linked',
          association_label: 'DEMO medicine · v2',
          care_review: { target_id: null, payload },
          proposal: { action: 'task', task: payload },
        },
      }}
      busy={false}
      onEvent={vi.fn()}
    />,
  );
  fireEvent.click(await screen.findByRole('button', { name: 'Review care record' }));
  expect(screen.getByRole('dialog').textContent).toContain('DEMO medicine · v2');
  expect(write).not.toHaveBeenCalled();
});
