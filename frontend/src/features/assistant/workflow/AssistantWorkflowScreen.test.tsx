// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { AssistantScreen } from '../conversation/AssistantScreen';
import { api } from '../../../api/client';
import { workflowApi, type WorkflowView } from '../../../api/assistantWorkflows';

vi.mock('../../../api/client', () => ({
  ApiError: class extends Error {},
  api: { recentTurns: vi.fn(), sendMessage: vi.fn() },
}));
vi.mock('../../../api/assistantWorkflows', () => ({
  workflowApi: {
    capabilities: vi.fn(),
    sendMessage: vi.fn(),
    event: vi.fn(),
    list: vi.fn(),
    originals: vi.fn(),
    view: vi.fn(),
  },
}));
afterEach(cleanup);
beforeEach(() => {
  localStorage.clear();
  vi.resetAllMocks();
  vi.mocked(api.recentTurns).mockResolvedValue([]);
  vi.mocked(workflowApi.list).mockResolvedValue([]);
  vi.mocked(workflowApi.originals).mockResolvedValue([]);
  vi.mocked(workflowApi.capabilities).mockResolvedValue({
    contract_version: 1,
    enabled: true,
    capabilities: [],
  });
});
const view: WorkflowView = {
  task_id: 'DEMO-task',
  revision: 1,
  capability_id: 'medication.enroll',
  state: 'choose_method',
  save_mode: 'allowed',
  storage_state: 'saved',
  prompt_key: 'assistant.enrollment.choose_method',
  visible_fields: {},
  missing_fields: ['method'],
  explanations: [],
  result_ref: null,
  actions: [
    {
      kind: 'choice',
      action_id: 'enrollment.method',
      options: [
        { value: 'manual', label_key: 'assistant.enrollment.manual' },
        { value: 'photo', label_key: 'assistant.enrollment.photo' },
      ],
    },
  ],
};

it('continues enrollment in the existing Assistant surface without legacy resending', async () => {
  vi.mocked(workflowApi.sendMessage).mockResolvedValue({
    reply: {
      message: 'DEMO choose entry method',
      intent: 'medication_enrollment',
      mode: 'workflow',
      tool_traces: [],
      session_id: 'DEMO-session',
      session_state: 'collecting',
      requires_confirmation: false,
    },
    workflow: view,
    explanations: [],
  });
  vi.mocked(workflowApi.event).mockResolvedValue({
    ...view,
    revision: 2,
    state: 'collecting',
    visible_fields: { method: 'manual' },
    actions: [],
    prompt_key: 'assistant.enrollment.provide_fields',
  });
  render(<AssistantScreen ownerId="DEMO-A" sessionId={null} onSession={vi.fn()} />);
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Add a medication' } });
  fireEvent.click(screen.getByRole('button', { name: 'Send' }));
  await screen.findByRole('button', { name: 'Enter manually' });
  fireEvent.click(screen.getByRole('button', { name: 'Enter manually' }));
  await screen.findByText('Continue with the remaining details.');
  expect(api.sendMessage).not.toHaveBeenCalled();
  expect(workflowApi.event).toHaveBeenCalledWith(
    'DEMO-task',
    expect.objectContaining({
      expected_revision: 1,
      kind: 'choose_method',
      values: { method: 'manual' },
    }),
    undefined,
  );
});

it('shows intentional revocation as no-save without reporting a storage outage', async () => {
  vi.mocked(workflowApi.sendMessage).mockResolvedValue({
    reply: {
      message: 'DEMO no-save answer',
      intent: 'clarification',
      mode: 'workflow',
      history_saved: false,
      tool_traces: [],
      session_id: 'DEMO-session',
      session_state: 'collecting',
      requires_confirmation: false,
    },
    workflow: { ...view, save_mode: 'ephemeral', storage_state: 'ephemeral' },
    explanations: [],
  });
  render(<AssistantScreen ownerId="DEMO-A" sessionId={null} onSession={vi.fn()} />);
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'DEMO request' } });
  fireEvent.click(screen.getByRole('button', { name: 'Send' }));
  await screen.findByText('DEMO no-save answer');
  expect(
    screen.queryByText('Could not save this conversation. Your answer is still available.'),
  ).toBeNull();
});
it('checks an uncertain source result through the trusted result event without resubmitting a save', async () => {
  const source = {
    ...view,
    capability_id: 'medication.source.add',
    state: 'awaiting_confirmation' as const,
    actions: [],
    missing_fields: [],
    result_ref: { kind: 'enrollment_task' as const, id: 'DEMO-source', version: 1 },
    prompt_key: 'assistant.source.changed',
  };
  vi.mocked(workflowApi.sendMessage).mockResolvedValue({
    reply: {
      message: 'DEMO source result needs checking',
      intent: 'medication_enrollment',
      mode: 'workflow',
      tool_traces: [],
      session_id: 'DEMO-session',
      session_state: 'collecting',
      requires_confirmation: false,
    },
    workflow: source,
    explanations: [],
  });
  vi.mocked(workflowApi.view).mockResolvedValue({ ...source, state: 'failed_recoverable' });
  vi.mocked(workflowApi.event).mockResolvedValue({
    ...source,
    revision: 2,
    result_ref: { ...source.result_ref, version: 2 },
  });
  render(<AssistantScreen ownerId="DEMO-A" sessionId={null} onSession={vi.fn()} />);
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'add a medication source' } });
  fireEvent.click(screen.getByRole('button', { name: 'Send' }));
  await screen.findByText('DEMO source result needs checking');
  fireEvent.click(screen.getByRole('button', { name: 'Check task status' }));
  await vi.waitFor(() =>
    expect(workflowApi.event).toHaveBeenCalledWith(
      'DEMO-task',
      expect.objectContaining({ kind: 'report_business_result', expected_revision: 1, values: {} }),
      undefined,
    ),
  );
});
