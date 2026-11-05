// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { api } from '../../../api/client';
import type { WorkflowView } from '../../../api/assistantWorkflows';
import type { DoseFollowUp, LateReportChallenge } from '../../../api/doseFollowUps';
import { AssistantWorkflow } from './AssistantWorkflow';
import { workflowChoice } from '../model/assistantWorkflowActions';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
const id = '00000000-0000-4000-8000-000000000099';
const item: DoseFollowUp = {
  occurrence_id: id,
  regimen_id: 'DEMO-plan',
  medication_id: 'DEMO-med',
  medication_name: 'DEMO historical medicine',
  due_at: '2026-10-26T12:00:00Z',
  dose_amount: 1,
  dose_unit: 'tablet',
  version_no: 1,
  can_report: true,
  report_id: null,
  intake_status: null,
  actual_administration_at: null,
  recorded_at: null,
  reason: null,
  notes: '',
};
const view: WorkflowView = {
  task_id: 'DEMO-late',
  revision: 2,
  capability_id: 'dose.late.review',
  state: 'awaiting_confirmation',
  save_mode: 'allowed',
  storage_state: 'saved',
  prompt_key: 'assistant.late.patient_review',
  input_fields: { occurrence_id: id, expected_version: 1 },
  visible_fields: { late_target: item as unknown as Record<string, never> },
  missing_fields: [],
  actions: [
    {
      kind: 'existing_review',
      component_key: 'existing_late_report',
      owned_ref: { kind: 'dose_occurrence', id, version: 1 },
      expected_version: 1,
    },
  ],
  explanations: [],
  result_ref: { kind: 'dose_occurrence', id, version: 1 },
};

function setup(fail = false) {
  vi.spyOn(api, 'lateReportHistory').mockResolvedValue({ original: null, corrections: [] });
  const ask = vi.spyOn(api, 'prepareLateReport').mockImplementation(async (_id, values) => ({
    challenge_id: 'DEMO-confirm',
    session_id: 'DEMO-session',
    expires_at: '2099-01-01T00:00:00Z',
    occurrence: item,
    proposed: values,
    timezone: 'Asia/Singapore',
  }));
  const save = vi.spyOn(api, 'confirmLateReport');
  if (fail) save.mockRejectedValue(new Error('DEMO lost response'));
  else
    save.mockImplementation(async (_id, summary) => ({
      ...summary.proposed,
      patient_id: 'DEMO-owner',
      occurrence_id: id,
      regimen_id: item.regimen_id,
      recorded_at: '2026-10-27T12:00:00Z',
      version: 1,
      idempotency_key: 'DEMO-key',
      ingestion_proven: false,
      visual_status: 'not_checked',
    }));
  return { ask, save };
}

async function review() {
  fireEvent.click(await screen.findByRole('button', { name: 'Review historical report' }));
  fireEvent.click(await screen.findAllByRole('radio').then((rows) => rows[0]!));
  fireEvent.change(screen.getByRole('combobox'), { target: { value: 'forgot_to_record' } });
  fireEvent.click(screen.getByRole('button', { name: 'Review report' }));
  await screen.findByRole('button', { name: 'Confirm report' });
}

it('opens only the selected original patient form and cancellation never submits', async () => {
  const { ask, save } = setup();
  render(<AssistantWorkflow view={view} busy={false} onEvent={vi.fn()} />);
  expect(ask).not.toHaveBeenCalled();
  await review();
  expect(ask).toHaveBeenCalledWith(id, expect.objectContaining({ expected_report_id: null }), {
    task_id: view.task_id,
    expected_revision: 2,
  });
  expect(document.activeElement).toBe(screen.getByRole('heading', { name: 'Review your report' }));
  fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' });
  expect(save).not.toHaveBeenCalled();
});
it('confirms separately with task binding and requests actual result readback', async () => {
  const { save } = setup();
  const send = vi.fn().mockResolvedValue({ ...view, state: 'completed', revision: 3 });
  render(<AssistantWorkflow view={view} busy={false} onEvent={send} />);
  await review();
  fireEvent.click(screen.getByRole('button', { name: 'Confirm report' }));
  await waitFor(() =>
    expect(save).toHaveBeenCalledWith(
      id,
      expect.objectContaining({ challenge_id: 'DEMO-confirm' }) as LateReportChallenge,
      { task_id: view.task_id, expected_revision: 2 },
    ),
  );
  await waitFor(() =>
    expect(send).toHaveBeenCalledWith(
      expect.objectContaining({ kind: 'report_business_result', values: {} }),
    ),
  );
});
it('retains an uncertain report and checks status without resubmitting', async () => {
  const { save } = setup(true);
  const send = vi.fn();
  render(<AssistantWorkflow view={view} busy={false} onEvent={send} />);
  await review();
  fireEvent.click(screen.getByRole('button', { name: 'Confirm report' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Check report result' }));
  await waitFor(() => expect(send).toHaveBeenCalled());
  expect(save).toHaveBeenCalledOnce();
});
it('offers no patient write in no-save mode', () => {
  const { ask } = setup();
  render(
    <AssistantWorkflow view={{ ...view, save_mode: 'ephemeral' }} busy={false} onEvent={vi.fn()} />,
  );
  expect(screen.queryByRole('button', { name: 'Review historical report' })).toBeNull();
  expect(ask).not.toHaveBeenCalled();
});
it('retains patient entries when result checking finds no saved report and requires a fresh summary', async () => {
  const { ask } = setup(true);
  const latest = { ...view, revision: 3 };
  const send = vi.fn().mockResolvedValue(latest);
  const { rerender } = render(<AssistantWorkflow view={view} busy={false} onEvent={send} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Review historical report' }));
  fireEvent.click((await screen.findAllByRole('radio'))[0]!);
  fireEvent.change(screen.getByRole('combobox'), { target: { value: 'forgot_to_record' } });
  fireEvent.change(screen.getByRole('textbox', { name: 'Notes (optional)' }), {
    target: { value: 'DEMO retained after response loss' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Review report' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Confirm report' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Check report result' }));
  await waitFor(() => expect(send).toHaveBeenCalled());
  rerender(<AssistantWorkflow view={latest} busy={false} onEvent={send} />);
  const notes = await screen.findByRole('textbox', { name: 'Notes (optional)' });
  expect((notes as HTMLTextAreaElement).value).toBe('DEMO retained after response loss');
  expect((screen.getByRole('combobox') as HTMLSelectElement).value).toBe('forgot_to_record');
  expect(screen.queryByRole('button', { name: 'Confirm report' })).toBeNull();
  const oldId = ask.mock.calls[0]![1].id;
  fireEvent.click(screen.getByRole('button', { name: 'Review report' }));
  await screen.findByRole('button', { name: 'Confirm report' });
  expect(ask.mock.calls.at(-1)![1].id).not.toBe(oldId);
  expect(ask.mock.calls.at(-1)![1].notes).toBe('DEMO retained after response loss');
});
it('accepts only the offered occurrence and report generation', () => {
  const action = {
    kind: 'choice' as const,
    action_id: 'late.target',
    options: [
      {
        value: `${id}:1:none`,
        label_key: 'assistant.late.select',
        label_text: item.medication_name,
      },
    ],
  };
  expect(workflowChoice(view, action, `${id}:1:none`)).toMatchObject({
    values: { occurrence_id: id, expected_version: 1, expected_report_id: null, page: 0 },
  });
  expect(() => workflowChoice(view, action, `${id}:2:none`)).toThrow();
});
