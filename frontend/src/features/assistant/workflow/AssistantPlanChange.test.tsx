// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { WorkflowView } from '../../../api/assistantWorkflows';
import { workflowChoice } from '../model/assistantWorkflowActions';
import { AssistantWorkflow } from './AssistantWorkflow';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
const id = '00000000-0000-4000-8000-000000000099';
const fields = {
  method: 'manual',
  medication_name: 'DEMO fixed product',
  dose_amount: 1,
  dose_unit: 'tablet',
  frequency_rule: { kind: 'daily', local_times: ['20:00'] },
};
const base: WorkflowView = {
  task_id: 'DEMO-change',
  revision: 2,
  capability_id: 'medication.plan.change',
  state: 'collecting',
  save_mode: 'allowed',
  storage_state: 'saved',
  prompt_key: 'assistant.plan_change.edit',
  visible_fields: {
    ...fields,
    original_plan: { regimen_id: id, version_no: 1, state: 'active' },
    change_inputs: {
      dose_amount: 1,
      dose_unit: 'tablet',
      frequency_rule: fields.frequency_rule,
      route: 'oral',
    },
  },
  input_fields: { regimen_id: id, expected_version: 1, expected_state: 'active', page: 0 },
  missing_fields: ['changed_instructions'],
  actions: [
    { kind: 'fields', schema_id: 'medication.enroll:v1', field_names: ['changed_instructions'] },
  ],
  explanations: [],
  result_ref: null,
};

it('accepts only the offered plan version and observed state', () => {
  const action = {
    kind: 'choice' as const,
    action_id: 'medication.change_target',
    options: [
      {
        value: `${id}:1:active`,
        label_key: 'assistant.medication.select_plan',
        label_text: 'DEMO / v1',
      },
    ],
  };
  expect(workflowChoice(base, action, `${id}:1:active`)).toMatchObject({
    kind: 'provide_fields',
    values: {
      regimen_id: id,
      expected_version: 1,
      expected_state: 'active',
      details: null,
      page: 0,
    },
  });
  expect(() => workflowChoice(base, action, `${id}:1:ended`)).toThrow();
  const send = vi.fn();
  render(
    <AssistantWorkflow
      view={{ ...base, visible_fields: {}, actions: [action] }}
      busy={false}
      onEvent={send}
    />,
  );
  fireEvent.click(screen.getByRole('button', { name: 'Choose plan: DEMO / v1' }));
  expect(send).toHaveBeenCalledOnce();
});

it('keeps product identity fixed and nests only changed clinical inputs with explicit clears', async () => {
  const send = vi.fn();
  render(<AssistantWorkflow view={base} busy={false} onEvent={send} />);
  expect(screen.getByRole('textbox', { name: 'Medication name' })).toHaveProperty('readOnly', true);
  expect(screen.queryByRole('textbox', { name: 'Product strength' })).toBeNull();
  fireEvent.change(screen.getByRole('spinbutton', { name: 'Amount per dose', hidden: true }), {
    target: { value: '2' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Use these details' }));
  await waitFor(() =>
    expect(send).toHaveBeenCalledWith(
      expect.objectContaining({
        kind: 'provide_fields',
        values: {
          details: expect.objectContaining({
            dose_amount: 2,
            route: 'oral',
            course_end_date: null,
          }),
        },
      }),
    ),
  );
  const details = send.mock.calls[0]![0].values.details;
  expect(details).not.toHaveProperty('medication_name');
  expect(details).not.toHaveProperty('dose_basis');
  expect(screen.getByText(/original plan remains active/i)).toBeTruthy();
});

it('does not create a draft on mount and offers preparation only after a changed complete preview', () => {
  const send = vi.fn();
  const { rerender } = render(<AssistantWorkflow view={base} busy={false} onEvent={send} />);
  expect(send).not.toHaveBeenCalled();
  expect(screen.queryByRole('button', { name: 'Review this medication' })).toBeNull();
  rerender(
    <AssistantWorkflow
      view={{ ...base, state: 'ready_for_review', missing_fields: [] }}
      busy={false}
      onEvent={send}
    />,
  );
  fireEvent.click(screen.getByRole('button', { name: 'Review this medication' }));
  expect(send).toHaveBeenCalledWith(
    expect.objectContaining({ kind: 'prepare_confirmation', values: {} }),
  );
});
