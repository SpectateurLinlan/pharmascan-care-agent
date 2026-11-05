// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { api } from '../../../api/client';
import { AssistantWorkflow } from './AssistantWorkflow';
import type { WorkflowView } from '../../../api/assistantWorkflows';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
const id = '00000000-0000-4000-8000-000000000099';
const view: WorkflowView = {
  task_id: 'DEMO-read',
  revision: 2,
  capability_id: 'medication.plan.view',
  state: 'collecting',
  save_mode: 'allowed',
  storage_state: 'saved',
  prompt_key: 'assistant.medication.read',
  visible_fields: {
    records: [
      {
        medication_id: id,
        display_name: 'DEMO actual recorded medicine',
        plans: [
          {
            regimen_id: 'DEMO-plan',
            version_no: 3,
            state: 'draft',
            dose_amount: 1,
            dose_unit: 'tablet',
            is_prn: false,
            frequency_rule: { kind: 'daily', local_times: ['20:00'] },
          },
        ],
      },
    ],
    page: 0,
    page_count: 1,
  },
  missing_fields: [],
  actions: [],
  explanations: [],
  result_ref: null,
};
const stop: WorkflowView = {
  ...view,
  capability_id: 'medication.plan.end',
  state: 'awaiting_confirmation',
  result_ref: { kind: 'regimen', id, version: 3 },
  actions: [
    {
      kind: 'existing_review',
      component_key: 'existing_plan_end',
      owned_ref: { kind: 'regimen', id, version: 3 },
      expected_version: 3,
    },
  ],
};

it('uses the independent stop confirmation and keeps failed requests pending', async () => {
  const end = vi.spyOn(api, 'endPlan').mockRejectedValue(new Error('DEMO stop failed'));
  const submit = vi.fn();
  render(<AssistantWorkflow view={stop} busy={false} onEvent={submit} />);
  fireEvent.click(screen.getByRole('button', { name: 'Stop tracking this regimen' }));
  expect(end).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
  expect(end).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Stop tracking this regimen' }));
  fireEvent.click(screen.getByRole('button', { name: 'Confirm stop' }));
  await screen.findByText('DEMO stop failed');
  expect(submit).not.toHaveBeenCalled();
});

it('reports a stop only after the existing patient API returns the matching ended plan', async () => {
  const end = vi.spyOn(api, 'endPlan').mockResolvedValue({ regimen_id: id, state: 'ended' });
  const submit = vi.fn();
  render(<AssistantWorkflow view={stop} busy={false} onEvent={submit} />);
  fireEvent.click(screen.getByRole('button', { name: 'Stop tracking this regimen' }));
  fireEvent.click(screen.getByRole('button', { name: 'Confirm stop' }));
  await waitFor(() =>
    expect(submit).toHaveBeenCalledWith(
      expect.objectContaining({ kind: 'report_business_result', values: {} }),
    ),
  );
  expect(end).toHaveBeenCalledWith(id, { task_id: 'DEMO-read', expected_revision: 2 });
});

it('shows the actual saved plan and its unfinished state inside the conversation', () => {
  render(<AssistantWorkflow view={view} busy={false} onEvent={vi.fn()} />);
  expect(screen.getByText('DEMO actual recorded medicine')).toBeTruthy();
  expect(screen.getByText('Draft')).toBeTruthy();
  expect(screen.getByText(/20:00/)).toBeTruthy();
  expect(screen.queryByRole('button', { name: /activate|confirm/i })).toBeNull();
});

it('selects only an offered owned medication with the visible workflow revision', () => {
  const submit = vi.fn();
  const picker = {
    ...view,
    prompt_key: 'assistant.medication.choose',
    missing_fields: ['medication_id'],
    actions: [
      {
        kind: 'choice' as const,
        action_id: 'medication.target',
        options: [
          {
            value: id,
            label_key: 'assistant.medication.select',
            label_text: 'DEMO actual recorded medicine',
          },
        ],
      },
    ],
  };
  render(<AssistantWorkflow view={picker} busy={false} onEvent={submit} />);
  fireEvent.click(
    screen.getByRole('button', { name: 'View record: DEMO actual recorded medicine' }),
  );
  expect(submit).toHaveBeenCalledWith(
    expect.objectContaining({
      kind: 'provide_fields',
      expected_revision: 2,
      values: { medication_id: id, page: 0 },
    }),
  );
});

it('describes saving a read task without implying that it creates a medication', () => {
  const submit = vi.fn();
  render(
    <AssistantWorkflow
      view={{ ...view, save_mode: 'ephemeral', storage_state: 'ephemeral' }}
      busy={false}
      onEvent={submit}
    />,
  );
  fireEvent.click(screen.getByRole('button', { name: 'Save this query' }));
  expect(submit).toHaveBeenCalledWith(expect.objectContaining({ kind: 'allow_save' }));
  expect(
    screen.queryByText(
      'Saving keeps these details as a draft. The plan still needs review and separate confirmation.',
    ),
  ).toBeNull();
});
