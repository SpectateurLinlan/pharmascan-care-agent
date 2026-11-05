// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { api, type ReportChallengeResponse } from '../../../api/client';
import type { WorkflowView } from '../../../api/assistantWorkflows';
import { AssistantWorkflow } from './AssistantWorkflow';
import { workflowChoice } from '../model/assistantWorkflowActions';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
const id = '00000000-0000-4000-8000-000000000099';
const view: WorkflowView = {
  task_id: 'DEMO-report',
  revision: 2,
  capability_id: 'dose.prn.report',
  state: 'awaiting_confirmation',
  save_mode: 'allowed',
  storage_state: 'saved',
  prompt_key: 'assistant.report.patient_review',
  input_fields: { regimen_id: id, expected_version: 1, page: 0 },
  visible_fields: {
    report_target: {
      regimen_id: id,
      version: 1,
      medication_name: 'DEMO PRN product',
      dose_amount: 1,
      dose_unit: 'tablet',
      is_prn: true,
    },
  },
  missing_fields: [],
  actions: [
    {
      kind: 'existing_review',
      component_key: 'existing_self_report',
      owned_ref: { kind: 'regimen', id, version: 1 },
      expected_version: 1,
    },
  ],
  explanations: [],
  result_ref: { kind: 'regimen', id, version: 1 },
};
const summary: ReportChallengeResponse = {
  challenge_id: 'DEMO-patient-confirmation',
  regimen_id: id,
  occurrence_id: null,
  session_id: 'DEMO-session',
  session_state: 'awaiting_confirmation',
  session_state_version: 1,
  expires_at: '2099-01-01T00:00:00Z',
  already_recorded: false,
  note: 'DEMO only',
  summary: {
    medication_display_name: 'DEMO PRN product',
    dose_amount: 1,
    dose_unit: 'tablet',
    regimen_version_no: 1,
    occurrence_due_at: null,
    local_due_time: null,
    local_timezone: 'Asia/Singapore',
    intake_status: 'reported_taken',
    intake_status_label: 'Patient reported taken',
    safety_notice: 'Self-report does not prove ingestion.',
    ingestion_proven: false,
    visual_status: 'not_checked',
  },
};

it('requests no challenge on mount and cancellation never records the patient choice', async () => {
  const ask = vi.spyOn(api, 'requestPrnReportChallenge').mockResolvedValue(summary);
  const save = vi.spyOn(api, 'submitPrnReport');
  render(<AssistantWorkflow view={view} busy={false} onEvent={vi.fn()} />);
  const taken = await screen.findByRole('button', { name: 'Taken' });
  expect(ask).not.toHaveBeenCalled();
  fireEvent.click(taken);
  await screen.findByRole('button', { name: 'Confirm record' });
  expect(ask).toHaveBeenCalledWith(
    expect.objectContaining({
      regimen_id: id,
      intake_status: 'Taken',
      idempotency_key: expect.stringMatching(/^report-/),
    }),
    { task_id: view.task_id, expected_revision: 2 },
  );
  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
  expect(save).not.toHaveBeenCalled();
});

it('confirms only the exact patient summary then requests actual workflow readback', async () => {
  vi.spyOn(api, 'requestPrnReportChallenge').mockResolvedValue(summary);
  const save = vi.spyOn(api, 'submitPrnReport').mockResolvedValue({
    event_id: 'DEMO-event',
    intake_status: 'reported_taken',
    visual_status: 'not_checked',
    already_recorded: false,
    ingestion_proven: false,
    note: 'DEMO only',
  });
  const send = vi.fn();
  render(<AssistantWorkflow view={view} busy={false} onEvent={send} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Taken' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Confirm record' }));
  await waitFor(() =>
    expect(save).toHaveBeenCalledWith(
      expect.objectContaining({ regimen_id: id, challenge_id: summary.challenge_id }),
      { task_id: view.task_id, expected_revision: 2 },
    ),
  );
  await waitFor(() =>
    expect(send).toHaveBeenCalledWith(
      expect.objectContaining({ kind: 'report_business_result', values: {} }),
    ),
  );
});

it('keeps an uncertain confirmation pending and checks its real result before a new attempt', async () => {
  vi.spyOn(api, 'requestPrnReportChallenge').mockResolvedValue(summary);
  const save = vi.spyOn(api, 'submitPrnReport').mockRejectedValue(new Error('DEMO response lost'));
  const send = vi.fn();
  render(<AssistantWorkflow view={view} busy={false} onEvent={send} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Taken' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Confirm record' }));
  await screen.findByRole('button', { name: 'Check report result' });
  expect(save).toHaveBeenCalledOnce();
  fireEvent.click(screen.getByRole('button', { name: 'Check report result' }));
  await waitFor(() =>
    expect(send).toHaveBeenCalledWith(
      expect.objectContaining({ kind: 'report_business_result', values: {} }),
    ),
  );
  expect(save).toHaveBeenCalledOnce();
});

it('hides patient report actions for no-save mode even if an old review action remains', async () => {
  const ask = vi.spyOn(api, 'requestPrnReportChallenge');
  render(
    <AssistantWorkflow
      view={{ ...view, save_mode: 'ephemeral', storage_state: 'ephemeral' }}
      busy={false}
      onEvent={vi.fn()}
    />,
  );
  await screen.findByText('Details stay on this page. Refreshing loses them.');
  expect(screen.queryByRole('button', { name: 'Taken' })).toBeNull();
  expect(ask).not.toHaveBeenCalled();
});

it('prepares only after the patient chooses an offered version and requests review', () => {
  const action = {
    kind: 'choice' as const,
    action_id: 'report.target',
    options: [
      {
        value: `${id}:1`,
        label_key: 'assistant.medication.select_plan',
        label_text: 'DEMO PRN product',
      },
    ],
  };
  expect(workflowChoice(view, action, `${id}:1`)).toMatchObject({
    values: { regimen_id: id, expected_version: 1, page: 0 },
  });
  expect(() => workflowChoice(view, action, `${id}:2`)).toThrow();
  const send = vi.fn();
  render(
    <AssistantWorkflow
      view={{
        ...view,
        state: 'ready_for_review',
        result_ref: null,
        actions: [],
        visible_fields: { medication_name: 'DEMO PRN product' },
      }}
      busy={false}
      onEvent={send}
    />,
  );
  expect(send).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Review dose report' }));
  expect(send).toHaveBeenCalledWith(
    expect.objectContaining({ kind: 'prepare_confirmation', values: {} }),
  );
});
