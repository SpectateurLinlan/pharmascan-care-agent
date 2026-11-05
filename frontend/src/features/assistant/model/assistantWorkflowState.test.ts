// @vitest-environment jsdom
import { expect, it } from 'vitest';
import { WorkflowMemory } from './assistantWorkflowState';
import type { WorkflowView } from '../../../api/assistantWorkflows';

const view: WorkflowView = {
  task_id: 'DEMO-task',
  revision: 1,
  capability_id: 'medication.enroll',
  state: 'collecting',
  save_mode: 'ephemeral',
  storage_state: 'ephemeral',
  prompt_key: 'assistant.enrollment.provide_fields',
  visible_fields: { method: 'manual', medication_name: 'DEMO-private-page-value' },
  missing_fields: ['dose_amount'],
  actions: [],
  explanations: [],
  result_ref: null,
};

it('keeps read results separate from closed page inputs when refreshing a no-save task', () => {
  const memory = new WorkflowMemory('DEMO-A');
  memory.remember({
    ...view,
    capability_id: 'medication.plan.view',
    input_fields: { page: 0 },
    visible_fields: { page: 0, records: [{ display_name: 'DEMO read result' }] },
  });
  expect(memory.ephemeral(view.task_id)).toEqual({
    capability_id: 'medication.plan.view',
    fields: { page: 0 },
  });
  expect(memory.get(view.task_id)?.visible_fields.records).toEqual([
    { display_name: 'DEMO read result' },
  ]);
});

it('keeps original File references and fields only in this owner page instance', () => {
  const memory = new WorkflowMemory('DEMO-A');
  memory.remember(view);
  const file = new File(['DEMO original bytes'], 'DEMO-label.png', { type: 'image/png' });
  const pending = memory.addFile(view.task_id, file, 'pharmacy_label');
  expect(memory.files(view.task_id)[0]!.file).toBe(file);
  expect(memory.addFile(view.task_id, file, 'pharmacy_label').upload_id).toBe(pending.upload_id);
  expect(memory.ephemeral(view.task_id)?.fields.medication_name).toBe('DEMO-private-page-value');
  expect(JSON.stringify(localStorage)).not.toContain('DEMO-private-page-value');
  const refreshed = new WorkflowMemory('DEMO-A');
  expect(refreshed.get(view.task_id)).toBeNull();
  expect(refreshed.files(view.task_id)).toEqual([]);
});

it('isolates returned views and clears File references when identity changes', () => {
  const memory = new WorkflowMemory('DEMO-A');
  memory.remember(view);
  const file = new File(['DEMO bytes'], 'DEMO.png', { type: 'image/png' });
  memory.addFile(view.task_id, file, 'package');
  memory.get(view.task_id)!.visible_fields.medication_name = 'DEMO forged local mutation';
  expect(memory.ephemeral(view.task_id)?.fields.medication_name).toBe('DEMO-private-page-value');
  memory.reset('DEMO-B');
  expect(memory.get(view.task_id)).toBeNull();
  expect(memory.files(view.task_id)).toEqual([]);
});

it('does not treat fields as review authority and never loses a File after failed saving', () => {
  const memory = new WorkflowMemory('DEMO-A');
  memory.remember(view);
  const file = new File(['DEMO bytes'], 'DEMO.png', { type: 'image/png' });
  const pending = memory.addFile(view.task_id, file, 'package');
  memory.remember({ ...view, revision: 2, save_mode: 'allowed', storage_state: 'save_failed' });
  expect(memory.files(view.task_id)[0]!.file).toBe(file);
  expect(memory.files(view.task_id)[0]!.upload_id).toBe(pending.upload_id);
  expect(memory.ephemeral(view.task_id)).toBeUndefined();
});

it('ignores stale saved responses and renews upload identity after saving is revoked', () => {
  const memory = new WorkflowMemory('DEMO-A');
  memory.remember({ ...view, save_mode: 'allowed', storage_state: 'saved' });
  const file = new File(['DEMO bytes'], 'DEMO.png', { type: 'image/png' });
  const pending = memory.addFile(view.task_id, file, 'package');
  memory.acknowledge(view.task_id, pending.upload_id, 'DEMO-original');
  memory.remember({ ...view, revision: 3 });
  memory.revokeUploads(view.task_id);
  expect(
    memory.remember({ ...view, revision: 2, save_mode: 'allowed', storage_state: 'saved' }),
  ).toBe(false);
  expect(memory.get(view.task_id)?.save_mode).toBe('ephemeral');
  expect(memory.files(view.task_id)[0]!.upload_id).not.toBe(pending.upload_id);
  expect(memory.files(view.task_id)[0]!.file).toBe(file);
});
