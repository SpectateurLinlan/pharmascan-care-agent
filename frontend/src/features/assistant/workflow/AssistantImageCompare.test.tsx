// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { workflowApi, type WorkflowView } from '../../../api/assistantWorkflows';
import { AssistantWorkflow } from './AssistantWorkflow';

vi.mock('../../media/PhotoAcquisition', () => ({
  PhotoAcquisition: ({
    file,
    onFile,
  }: {
    file: File | null;
    onFile: (file: File | null) => void;
  }) => (
    <>
      <input
        type="file"
        aria-label="DEMO comparison photo"
        onChange={(event) => onFile(event.target.files?.[0] ?? null)}
      />
      {file ? <p>{file.name}</p> : null}
    </>
  ),
}));
vi.mock('../../../api/assistantWorkflows', async (load) => {
  const module = await load<typeof import('../../../api/assistantWorkflows')>();
  return {
    ...module,
    workflowApi: {
      ...module.workflowApi,
      compareImage: vi.fn(),
      uploadComparisonOriginal: vi.fn(),
    },
  };
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.clearAllMocks();
});
const source = '00000000-0000-4000-8000-000000000100';
const base: WorkflowView = {
  task_id: 'DEMO-compare-task',
  revision: 1,
  capability_id: 'image.compare',
  state: 'collecting',
  save_mode: 'allowed',
  storage_state: 'saved',
  prompt_key: 'assistant.compare.collect',
  input_fields: { intent: 'identify' },
  visible_fields: {},
  missing_fields: ['source_image'],
  actions: [
    {
      kind: 'choice',
      action_id: 'compare.intent',
      options: [
        { value: 'personal', label_key: 'assistant.compare.personal' },
        { value: 'identify', label_key: 'assistant.compare.identify' },
      ],
    },
  ],
  explanations: [],
  result_ref: null,
};
const saved: WorkflowView = {
  ...base,
  revision: 2,
  state: 'ready_for_review',
  input_fields: { intent: 'identify', source_attachment_id: source },
  missing_fields: [],
};
const file = new File(['DEMO comparison bytes'], 'DEMO.png', { type: 'image/png' });

async function pick() {
  fireEvent.change(await screen.findByLabelText('DEMO comparison photo'), {
    target: { files: [file] },
  });
}

const unknown = {
  intent: 'identify',
  decision: 'unknown',
  reason_key: 'no_reviewed_reference',
  selected_medication: null,
  candidates: [{ name: 'DEMO catalogue name', strength: 'DEMO 1 mg', market: 'US' }],
  safe_to_take: false,
  ingestion_proven: false,
  count_reliable: false,
} as const;

it('holds a no-save File across explicit saving without processing on select or save', async () => {
  const send = vi.fn().mockResolvedValue({ ...base, revision: 2 });
  const mounted = render(
    <AssistantWorkflow
      view={{ ...base, save_mode: 'ephemeral', storage_state: 'ephemeral' }}
      busy={false}
      onEvent={send}
      onView={vi.fn()}
    />,
  );
  await pick();
  fireEvent.click(await screen.findByRole('button', { name: 'Save photo check draft' }));
  await waitFor(() =>
    expect(send).toHaveBeenCalledWith(expect.objectContaining({ kind: 'allow_save' })),
  );
  mounted.rerender(
    <AssistantWorkflow
      view={{ ...base, revision: 2 }}
      busy={false}
      onEvent={send}
      onView={vi.fn()}
    />,
  );
  expect(screen.getByText(file.name)).toBeTruthy();
  expect(workflowApi.compareImage).not.toHaveBeenCalled();
  expect(workflowApi.uploadComparisonOriginal).not.toHaveBeenCalled();
});

it('keeps the File after original saving fails and permits an explicit status check', async () => {
  vi.mocked(workflowApi.uploadComparisonOriginal).mockRejectedValue(
    new Error('DEMO storage failed'),
  );
  render(<AssistantWorkflow view={base} busy={false} onEvent={vi.fn()} onView={vi.fn()} />);
  await pick();
  fireEvent.click(await screen.findByRole('button', { name: 'Save comparison original' }));
  expect(await screen.findByRole('alert')).toBeTruthy();
  expect(screen.getByText(file.name)).toBeTruthy();
  expect(workflowApi.compareImage).not.toHaveBeenCalled();
  expect(screen.getByRole('button', { name: 'Check original save status' })).toBeTruthy();
});

it('uses a new original upload key after saving is revoked and enabled again', async () => {
  vi.mocked(workflowApi.uploadComparisonOriginal).mockResolvedValue({
    workflow: saved,
    attachment: {
      id: source,
      task_id: base.task_id,
      original_checksum: 'a'.repeat(64),
      content_type: 'image/png',
      byte_size: 20,
      state: 'saved',
      extraction_status: 'not_requested',
      reason: null,
      cleanup_pending: false,
    },
  });
  const mounted = render(
    <AssistantWorkflow view={base} busy={false} onEvent={vi.fn()} onView={vi.fn()} />,
  );
  await pick();
  fireEvent.click(await screen.findByRole('button', { name: 'Save comparison original' }));
  await waitFor(() => expect(workflowApi.uploadComparisonOriginal).toHaveBeenCalledTimes(1));
  await waitFor(() =>
    expect(screen.getByRole('button', { name: 'Save comparison original' })).toHaveProperty(
      'disabled',
      false,
    ),
  );
  mounted.rerender(
    <AssistantWorkflow
      view={{ ...base, revision: 3, save_mode: 'ephemeral', storage_state: 'ephemeral' }}
      busy={false}
      onEvent={vi.fn()}
      onView={vi.fn()}
    />,
  );
  mounted.rerender(
    <AssistantWorkflow
      view={{ ...base, revision: 4 }}
      busy={false}
      onEvent={vi.fn()}
      onView={vi.fn()}
    />,
  );
  fireEvent.click(await screen.findByRole('button', { name: 'Save comparison original' }));
  await waitFor(() => expect(workflowApi.uploadComparisonOriginal).toHaveBeenCalledTimes(2));
  const calls = vi.mocked(workflowApi.uploadComparisonOriginal).mock.calls;
  expect(calls[0]![1]).not.toBe(calls[1]![1]);
  expect(screen.getByText(file.name)).toBeTruthy();
});

it('requires explicit processing consent and loads the retained original only when checking', async () => {
  vi.mocked(workflowApi.compareImage).mockResolvedValue(unknown);
  const blob = vi
    .spyOn(workflowApi, 'originalBlob')
    .mockResolvedValue(new Blob(['DEMO raw original'], { type: 'image/png' }));
  render(<AssistantWorkflow view={saved} busy={false} onEvent={vi.fn()} onView={vi.fn()} />);
  const check = await screen.findByRole('button', { name: 'Check photo' });
  expect(check).toHaveProperty('disabled', true);
  expect(blob).not.toHaveBeenCalled();
  fireEvent.click(
    screen.getByRole('checkbox', { name: 'I allow this photo to be sent for this visual check.' }),
  );
  fireEvent.click(check);
  expect(await screen.findByText('DEMO catalogue name · DEMO 1 mg (US catalogue)')).toBeTruthy();
  expect(blob).toHaveBeenCalledWith(base.task_id, source);
  expect(workflowApi.compareImage).toHaveBeenCalledWith(
    base.task_id,
    expect.any(File),
    2,
    true,
    undefined,
  );
  expect(
    screen.getByText('Appearance cannot confirm medication identity, dose, safe use or ingestion.'),
  ).toBeTruthy();
});

it('discards a late provider result after saving is revoked while retaining the page File', async () => {
  let resolve!: (value: typeof unknown) => void;
  vi.mocked(workflowApi.compareImage).mockReturnValue(
    new Promise((done) => {
      resolve = done;
    }),
  );
  const view = {
    ...base,
    save_mode: 'ephemeral' as const,
    storage_state: 'ephemeral' as const,
    state: 'ready_for_review' as const,
  };
  const mounted = render(
    <AssistantWorkflow view={view} busy={false} onEvent={vi.fn()} onView={vi.fn()} />,
  );
  await pick();
  fireEvent.click(screen.getByRole('checkbox'));
  fireEvent.click(screen.getByRole('button', { name: 'Check photo' }));
  await waitFor(() => expect(workflowApi.compareImage).toHaveBeenCalled());
  mounted.rerender(
    <AssistantWorkflow
      view={{ ...view, revision: 2, input_fields: { intent: 'personal' } }}
      busy={false}
      onEvent={vi.fn()}
      onView={vi.fn()}
    />,
  );
  resolve(unknown);
  await waitFor(() =>
    expect(screen.getByRole('button', { name: 'Check photo' })).toHaveProperty('disabled', true),
  );
  expect(screen.queryByText(/DEMO catalogue name/)).toBeNull();
  expect(screen.getByText(file.name)).toBeTruthy();
});

it('shows an unavailable result distinctly and does not automatically retry a provider', async () => {
  vi.mocked(workflowApi.compareImage).mockResolvedValue({
    ...unknown,
    decision: 'unavailable',
    reason_key: 'service_unavailable',
    candidates: [],
  });
  render(
    <AssistantWorkflow
      view={{ ...base, save_mode: 'ephemeral', storage_state: 'ephemeral' }}
      busy={false}
      onEvent={vi.fn()}
      onView={vi.fn()}
    />,
  );
  await pick();
  fireEvent.click(screen.getByRole('checkbox'));
  fireEvent.click(screen.getByRole('button', { name: 'Check photo' }));
  expect(
    await screen.findByText(
      'The photo service is unavailable. Your photo is retained; no identity conclusion was reached.',
    ),
  ).toBeTruthy();
  expect(workflowApi.compareImage).toHaveBeenCalledTimes(1);
});

it('changes the intent through typed offered choices without starting processing', async () => {
  const send = vi
    .fn()
    .mockResolvedValue({ ...base, revision: 2, input_fields: { intent: 'personal' } });
  render(<AssistantWorkflow view={base} busy={false} onEvent={send} onView={vi.fn()} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Compare with personal references' }));
  await waitFor(() =>
    expect(send).toHaveBeenCalledWith(
      expect.objectContaining({
        kind: 'provide_fields',
        values: { intent: 'personal', regimen_id: null, page: 0 },
      }),
    ),
  );
  expect(workflowApi.compareImage).not.toHaveBeenCalled();
});
