import { expect, it } from 'vitest';
import { workflowChoice } from './assistantWorkflowActions';
import type { WorkflowView, UIAction } from '../../../api/assistantWorkflows';

const view = {
  task_id: 'DEMO-task',
  capability_id: 'medication.enroll',
  revision: 3,
} as WorkflowView;
it('keeps the source-registration deletion reference distinct from a clinical plan', () => {
  const id = '00000000-0000-4000-8000-000000000099';
  const action: Extract<UIAction, { kind: 'choice' }> = {
    kind: 'choice',
    action_id: 'medication.delete_target',
    options: [{ value: `source:${id}:2`, label_key: 'assistant.medication.select_draft' }],
  };
  expect(
    workflowChoice({ ...view, capability_id: 'medication.draft.delete' }, action, `source:${id}:2`),
  ).toMatchObject({
    kind: 'provide_fields',
    values: { kind: 'source', target_id: id, expected_version: 2 },
  });
  expect(() =>
    workflowChoice({ ...view, capability_id: 'medication.draft.delete' }, action, `draft:${id}:2`),
  ).toThrow();
});
it('binds a stop choice to the offered plan version and rejects unoffered versions', () => {
  const id = '00000000-0000-4000-8000-000000000099';
  const action: Extract<UIAction, { kind: 'choice' }> = {
    kind: 'choice',
    action_id: 'medication.end_target',
    options: [
      {
        value: `${id}:3`,
        label_key: 'assistant.medication.select_plan',
        label_text: 'DEMO owned plan v3',
      },
    ],
  };
  expect(
    workflowChoice({ ...view, capability_id: 'medication.plan.end' }, action, `${id}:3`),
  ).toMatchObject({ kind: 'provide_fields', values: { regimen_id: id, expected_version: 3 } });
  expect(() =>
    workflowChoice({ ...view, capability_id: 'medication.plan.end' }, action, `${id}:4`),
  ).toThrow();
});
it('selects only an offered product from an exact original and candidate index', () => {
  const id = '00000000-0000-4000-8000-000000000099';
  const action: Extract<UIAction, { kind: 'choice' }> = {
    kind: 'choice',
    action_id: 'enrollment.source_product',
    options: [
      {
        value: `${id}:1`,
        label_key: 'assistant.enrollment.source_product',
        label_text: 'DEMO product 200mg',
      },
    ],
  };
  expect(workflowChoice(view, action, `${id}:1`)).toMatchObject({
    kind: 'select_candidate',
    values: { source_attachment_id: id, source_candidate_index: 1 },
  });
  expect(() => workflowChoice(view, action, `${id}:0`)).toThrow();
});
it('dispatches only an offered owned-record choice and never treats its display label as code', () => {
  const id = '00000000-0000-4000-8000-000000000012';
  const action: Extract<UIAction, { kind: 'choice' }> = {
    kind: 'choice',
    action_id: 'enrollment.duplicate',
    options: [
      { value: id, label_key: 'assistant.enrollment.reuse_existing', label_text: 'DEMO product' },
      { value: 'different_product', label_key: 'assistant.enrollment.different_product' },
    ],
  };
  expect(workflowChoice(view, action, id)).toMatchObject({
    kind: 'select_candidate',
    expected_revision: 3,
    values: { existing_medication_id: id },
  });
  expect(workflowChoice(view, action, 'different_product')).toMatchObject({
    kind: 'select_candidate',
    values: { choice: 'different_product' },
  });
  expect(() => workflowChoice(view, action, 'not-an-offered-id')).toThrow();
});
it('dispatches a distinct-strength choice only when the server offers it', () => {
  const action: Extract<UIAction, { kind: 'choice' }> = {
    kind: 'choice',
    action_id: 'enrollment.duplicate',
    options: [{ value: 'distinct_product', label_key: 'assistant.enrollment.distinct_product' }],
  };
  expect(workflowChoice(view, action, 'distinct_product')).toMatchObject({
    kind: 'select_candidate',
    values: { choice: 'distinct_product' },
  });
});
