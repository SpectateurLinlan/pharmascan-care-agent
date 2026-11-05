// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { AssistantScreen } from '../conversation/AssistantScreen';
import { api } from '../../../api/client';
import { workflowApi, type WorkflowView } from '../../../api/assistantWorkflows';

vi.mock('../../../api/client', () => ({
  ApiError: class extends Error {},
  api: {
    recentTurns: vi.fn(),
    sendMessage: vi.fn(),
    checkInput: vi.fn(),
    sourcePreview: vi.fn(),
    newConversation: vi.fn(),
    resumeConversation: vi.fn(),
    conversation: vi.fn(),
  },
}));
vi.mock('../../../api/assistantWorkflows', () => ({
  workflowApi: {
    capabilities: vi.fn(),
    sendMessage: vi.fn(),
    event: vi.fn(),
    list: vi.fn(),
    originals: vi.fn(),
    originalBlob: vi.fn(),
    uploadOriginal: vi.fn(),
    previewImage: vi.fn(),
    view: vi.fn(),
    preview: vi.fn(),
    retryCleanup: vi.fn(),
    resumeDraft: vi.fn(),
  },
}));
afterEach(cleanup);
beforeEach(() => {
  localStorage.clear();
  vi.resetAllMocks();
  vi.mocked(api.recentTurns).mockResolvedValue([]);
  vi.mocked(api.checkInput).mockResolvedValue({
    image_type: 'printed',
    checked: true,
    abstained: false,
    suggested_workflow: 'ask_patient',
    message: 'DEMO existing photo flow',
  });
  vi.mocked(workflowApi.capabilities).mockResolvedValue({
    contract_version: 1,
    enabled: true,
    capabilities: [],
  });
  vi.mocked(workflowApi.list).mockResolvedValue([]);
  vi.mocked(workflowApi.originals).mockResolvedValue([]);
  localStorage.setItem('pharmascan.image-processing.v1.DEMO-A', 'allowed');
});
const view: WorkflowView = {
  task_id: 'DEMO-task',
  workspace_id: 'DEMO-workspace',
  conversation_id: null,
  revision: 1,
  capability_id: 'medication.enroll',
  state: 'collecting',
  save_mode: 'allowed',
  storage_state: 'saved',
  prompt_key: 'assistant.enrollment.upload_source',
  visible_fields: { method: 'photo' },
  missing_fields: ['source_image'],
  explanations: [],
  result_ref: null,
  actions: [{ kind: 'upload', action_id: 'source_image', processing_consent_required: true }],
};
const reply = {
  message: 'DEMO choose a source photo',
  intent: 'medication_enrollment',
  mode: 'workflow',
  tool_traces: [],
  session_id: 'DEMO-session',
  session_state: 'collecting',
  requires_confirmation: false,
};

async function start(task: WorkflowView = view, onChanged: () => void = () => undefined) {
  vi.mocked(workflowApi.sendMessage).mockResolvedValue({ reply, workflow: task, explanations: [] });
  render(
    <AssistantScreen ownerId="DEMO-A" sessionId={null} onSession={vi.fn()} onChanged={onChanged} />,
  );
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Add a medication' } });
  fireEvent.click(screen.getByRole('button', { name: 'Send' }));
  await screen.findByText('DEMO choose a source photo');
}

function attach(file: File) {
  fireEvent.change(screen.getByLabelText('Choose a photo'), { target: { files: [file] } });
}

it('opens the original saved enrollment returned by the guarded recovery endpoint', async () => {
  const recovery: WorkflowView = {
    ...view,
    capability_id: 'medication.draft.resume',
    visible_fields: { regimen_id: 'DEMO-regimen' },
    missing_fields: [],
    actions: [
      {
        kind: 'resume_task',
        owned_ref: { kind: 'regimen', id: 'DEMO-regimen', version: 1 },
        expected_version: 1,
      },
    ],
  };
  const restored: WorkflowView = {
    ...view,
    task_id: 'DEMO-original-task',
    revision: 5,
    prompt_key: 'assistant.enrollment.patient_review',
    state: 'awaiting_confirmation',
    actions: [],
    visible_fields: { method: 'manual', medication_name: 'DEMO original progress' },
  };
  vi.mocked(workflowApi.resumeDraft).mockResolvedValue(restored);
  vi.mocked(workflowApi.view).mockResolvedValue(restored);
  vi.mocked(api.newConversation).mockResolvedValue({
    session_id: 'DEMO-new-session',
    patient_id: 'DEMO-A',
    demo_only: true,
    seeded_medication_count: 0,
    note: 'DEMO-only recovery test',
  });
  await start(recovery);
  fireEvent.click(screen.getByRole('button', { name: 'Continue original enrollment' }));
  await waitFor(() => expect(workflowApi.resumeDraft).toHaveBeenCalledWith('DEMO-task', 1));
  await screen.findByText(
    'The draft is saved. Check the original instructions, then confirm separately.',
  );
  expect(workflowApi.event).not.toHaveBeenCalled();
});

it('sends only closed no-save inputs when pausing a query with derived display records', async () => {
  const query: WorkflowView = {
    ...view,
    capability_id: 'medication.setup.list',
    save_mode: 'ephemeral',
    storage_state: 'ephemeral',
    visible_fields: { records: [], source_tasks: [], page: 0, page_count: 1 },
    input_fields: { page: 0 },
    actions: [],
    missing_fields: [],
  };
  vi.mocked(workflowApi.event).mockResolvedValue({ ...query, revision: 2, state: 'suspended' });
  await start(query);
  fireEvent.click(screen.getByRole('button', { name: 'Pause task' }));
  await waitFor(() =>
    expect(workflowApi.event).toHaveBeenCalledWith(
      'DEMO-task',
      expect.objectContaining({ kind: 'pause' }),
      { capability_id: 'medication.setup.list', fields: { page: 0 } },
    ),
  );
});

it('refreshes application records when status inspection recovers a completed deletion', async () => {
  const pending = {
    ...view,
    capability_id: 'medication.draft.delete',
    state: 'awaiting_confirmation' as const,
    visible_fields: { kind: 'draft', target_id: 'DEMO-draft', records: [], source_tasks: [] },
    actions: [],
  };
  const changed = vi.fn();
  vi.mocked(workflowApi.view).mockResolvedValue({
    ...pending,
    state: 'completed',
    prompt_key: 'assistant.medication.deleted',
    visible_fields: { ...pending.visible_fields, deleted: true },
  });
  await start(pending, changed);
  expect(changed).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Check task status' }));
  await screen.findByText('The draft was deleted. Confirmed history is retained.');
  expect(changed).toHaveBeenCalledOnce();
});

it.each(['completed', 'cancelled'] as const)(
  'routes a new photo through the existing message flow after enrollment is %s',
  async (state) => {
    await start({ ...view, state, actions: [] });
    vi.mocked(workflowApi.sendMessage).mockResolvedValue({
      reply: { ...reply, message: 'DEMO later photo response' },
      workflow: null,
      explanations: [],
    });
    const file = new File(['DEMO later photo'], 'DEMO-later.png', { type: 'image/png' });
    attach(file);
    fireEvent.click(screen.getByRole('button', { name: 'Send' }));
    await screen.findByText('DEMO later photo response');
    expect(api.checkInput).toHaveBeenCalledWith(file);
    expect(workflowApi.uploadOriginal).not.toHaveBeenCalled();
  },
);

it('requires the ordinary photo consent after enrollment has finished', async () => {
  localStorage.removeItem('pharmascan.image-processing.v1.DEMO-A');
  await start({ ...view, state: 'completed', actions: [] });
  attach(new File(['DEMO later photo'], 'DEMO-later.png', { type: 'image/png' }));
  expect(screen.getByRole('button', { name: 'Send' })).toHaveProperty('disabled', true);
  expect(
    screen.getByRole('checkbox', {
      name: 'Allow photo processing. The image is not saved; extracted details may appear in saved chats.',
    }),
  ).toBeTruthy();
  expect(api.checkInput).not.toHaveBeenCalled();
});

it('uses successful no-save photo proposals as page fields and revalidates without saving them', async () => {
  const fields = {
    method: 'photo',
    medication_name: 'DEMO page photo',
    dose_amount: 1,
    dose_unit: 'tablet',
    page_photo_previewed: true,
  };
  const collected = {
    ...view,
    revision: 2,
    save_mode: 'ephemeral' as const,
    storage_state: 'ephemeral' as const,
    visible_fields: fields,
    missing_fields: ['frequency_rule'],
    prompt_key: 'assistant.enrollment.provide_fields',
    actions: [
      {
        kind: 'fields' as const,
        schema_id: 'medication.enroll:v1',
        field_names: ['frequency_rule'],
      },
    ],
  };
  vi.mocked(workflowApi.previewImage).mockResolvedValue({
    task_id: view.task_id,
    revision: 2,
    capability_id: view.capability_id,
    save_mode: 'ephemeral',
    storage_state: 'ephemeral',
    outcome: 'success',
    reason: null,
    preview: null,
    fields,
  });
  vi.mocked(workflowApi.preview).mockResolvedValue(collected);
  await start({ ...view, save_mode: 'ephemeral', storage_state: 'ephemeral' });
  attach(new File(['DEMO bytes'], 'DEMO-page.png', { type: 'image/png' }));
  fireEvent.click(screen.getByRole('button', { name: 'Send' }));
  await waitFor(() =>
    expect(workflowApi.preview).toHaveBeenCalledWith(view.task_id, {
      capability_id: view.capability_id,
      fields,
    }),
  );
  await screen.findByLabelText('Schedule');
  expect(workflowApi.uploadOriginal).not.toHaveBeenCalled();
  expect(JSON.stringify({ ...localStorage })).not.toContain('DEMO page photo');
});

it('saves the original before recognition, retains the File on save failure and reuses its upload ID', async () => {
  const uploaded = {
    attachment: {
      id: 'DEMO-original',
      task_id: view.task_id,
      original_checksum: 'DEMO-checksum',
      content_type: 'image/png' as const,
      byte_size: 20,
      state: 'saved' as const,
      extraction_status: 'failed' as const,
      reason: 'provider_unavailable',
      cleanup_pending: false,
    },
    workflow: {
      ...view,
      revision: 3,
      state: 'failed_recoverable' as const,
      prompt_key: 'assistant.enrollment.extraction_failed',
    },
  };
  vi.mocked(workflowApi.uploadOriginal)
    .mockRejectedValueOnce(new Error('DEMO save unavailable'))
    .mockResolvedValueOnce(uploaded);
  await start();
  const file = new File(['DEMO original bytes'], 'DEMO-original.png', { type: 'image/png' });
  attach(file);
  fireEvent.click(screen.getByRole('button', { name: 'Send' }));
  await waitFor(() => expect(workflowApi.uploadOriginal).toHaveBeenCalled());
  await screen.findByText('DEMO save unavailable');
  expect(screen.getAllByText('DEMO-original.png').length).toBeGreaterThan(0);
  const first = vi.mocked(workflowApi.uploadOriginal).mock.calls[0]!;
  fireEvent.click(screen.getByRole('button', { name: 'Dismiss' }));
  fireEvent.click(screen.getByRole('button', { name: 'Send' }));
  await screen.findByText(
    'The original photo is saved, but its medication details could not be read.',
  );
  const second = vi.mocked(workflowApi.uploadOriginal).mock.calls[1]!;
  expect(first[1]).toBe(second[1]);
  expect(first[2]).toBe(file);
  expect(second[2]).toBe(file);
  expect(api.checkInput).not.toHaveBeenCalled();
  expect(api.sourcePreview).not.toHaveBeenCalled();
});

it('keeps a no-save photo on the page and uploads it only after explicit allow-save', async () => {
  const temporary = {
    ...view,
    save_mode: 'ephemeral' as const,
    storage_state: 'ephemeral' as const,
  };
  vi.mocked(workflowApi.previewImage).mockResolvedValue({
    task_id: view.task_id,
    revision: 2,
    capability_id: view.capability_id,
    save_mode: 'ephemeral',
    storage_state: 'ephemeral',
    outcome: 'failed',
    reason: 'provider_unavailable',
    preview: null,
  });
  vi.mocked(workflowApi.event).mockResolvedValue({ ...view, revision: 3 });
  vi.mocked(workflowApi.uploadOriginal).mockResolvedValue({
    attachment: {
      id: 'DEMO-original',
      task_id: view.task_id,
      original_checksum: 'DEMO-checksum',
      content_type: 'image/png',
      byte_size: 20,
      state: 'saved',
      extraction_status: 'failed',
      reason: 'provider_unavailable',
      cleanup_pending: false,
    },
    workflow: {
      ...view,
      revision: 5,
      state: 'failed_recoverable',
      prompt_key: 'assistant.enrollment.extraction_failed',
    },
  });
  await start(temporary);
  const file = new File(['DEMO private photo bytes'], 'DEMO-private.png', { type: 'image/png' });
  attach(file);
  fireEvent.click(screen.getByRole('button', { name: 'Send' }));
  await waitFor(() => expect(workflowApi.previewImage).toHaveBeenCalled());
  await screen.findByText('The original photo is not saved. Refreshing loses the page copy.');
  expect(workflowApi.uploadOriginal).not.toHaveBeenCalled();
  expect(api.checkInput).not.toHaveBeenCalled();
  expect(JSON.stringify(localStorage)).not.toContain('DEMO-private');
  fireEvent.click(screen.getByRole('button', { name: 'Save this medication and continue review' }));
  await screen.findByText(
    'The original photo is saved, but its medication details could not be read.',
  );
  expect(workflowApi.event).toHaveBeenCalledWith(
    view.task_id,
    expect.objectContaining({ kind: 'allow_save' }),
    expect.objectContaining({ fields: { method: 'photo' } }),
  );
  expect(vi.mocked(workflowApi.uploadOriginal).mock.calls[0]![2]).toBe(file);
});

it('can save an allowed original without consenting to recognition and explains that retention', async () => {
  localStorage.removeItem('pharmascan.image-processing.v1.DEMO-A');
  vi.mocked(workflowApi.uploadOriginal).mockResolvedValue({
    attachment: {
      id: 'DEMO-original',
      task_id: view.task_id,
      original_checksum: 'DEMO-checksum',
      content_type: 'image/png',
      byte_size: 20,
      state: 'saved',
      extraction_status: 'consent_required',
      reason: 'processing_consent_required',
      cleanup_pending: false,
    },
    workflow: { ...view, revision: 2, prompt_key: 'assistant.enrollment.processing_consent' },
  });
  await start();
  attach(new File(['DEMO bytes'], 'DEMO-original.png', { type: 'image/png' }));
  expect(
    screen.getByRole('checkbox', {
      name: 'Allow photo processing. The original will be saved with this task.',
    }),
  ).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Send' })).not.toHaveProperty('disabled', true);
  fireEvent.click(screen.getByRole('button', { name: 'Send' }));
  await screen.findByText(
    'The original photo is saved. Allow photo processing if you want recognition.',
  );
  expect(vi.mocked(workflowApi.uploadOriginal).mock.calls[0]![5]).toBe(false);
  expect(api.checkInput).not.toHaveBeenCalled();
});

it('includes a selected page photo when allow-save is chosen before any preview', async () => {
  localStorage.removeItem('pharmascan.image-processing.v1.DEMO-A');
  vi.mocked(workflowApi.event).mockResolvedValue({ ...view, revision: 2 });
  vi.mocked(workflowApi.uploadOriginal).mockResolvedValue({
    attachment: {
      id: 'DEMO-original',
      task_id: view.task_id,
      original_checksum: 'DEMO-checksum',
      content_type: 'image/png',
      byte_size: 20,
      state: 'saved',
      extraction_status: 'consent_required',
      reason: 'processing_consent_required',
      cleanup_pending: false,
    },
    workflow: { ...view, revision: 3, prompt_key: 'assistant.enrollment.processing_consent' },
  });
  await start({ ...view, save_mode: 'ephemeral', storage_state: 'ephemeral' });
  const file = new File(['DEMO bytes'], 'DEMO-original.png', { type: 'image/png' });
  attach(file);
  fireEvent.click(screen.getByRole('button', { name: 'Save this medication and continue review' }));
  await waitFor(() => expect(workflowApi.uploadOriginal).toHaveBeenCalled());
  expect(vi.mocked(workflowApi.uploadOriginal).mock.calls[0]![2]).toBe(file);
});

it('restores an owned saved task after refresh using its original workspace', async () => {
  const restored = {
    ...view,
    revision: 3,
    visible_fields: { method: 'photo', medication_name: 'DEMO restored' },
    state: 'failed_recoverable' as const,
    prompt_key: 'assistant.enrollment.extraction_failed',
  };
  vi.mocked(workflowApi.list).mockResolvedValue([restored]);
  vi.mocked(workflowApi.view).mockResolvedValue(restored);
  vi.mocked(api.newConversation).mockResolvedValue({
    patient_id: 'DEMO-A',
    session_id: 'DEMO-fresh',
    demo_only: true,
    seeded_medication_count: 0,
    note: 'DEMO',
  });
  vi.mocked(workflowApi.sendMessage).mockResolvedValue({
    reply: { ...reply, message: 'DEMO continued saved task' },
    workflow: restored,
    explanations: [],
  });
  render(<AssistantScreen ownerId="DEMO-A" sessionId={null} onSession={vi.fn()} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Unfinished tasks' }));
  fireEvent.click(screen.getByRole('button', { name: 'Resume task: DEMO restored' }));
  await screen.findByText(
    'The original photo is saved, but its medication details could not be read.',
  );
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'DEMO continue' } });
  fireEvent.click(screen.getByRole('button', { name: 'Send' }));
  await screen.findByText('DEMO continued saved task');
  expect(workflowApi.sendMessage).toHaveBeenCalledWith(
    expect.objectContaining({ task_id: view.task_id, workspace_id: view.workspace_id }),
  );
});

it('explains no-save refresh loss without pretending its photo or fields were recovered', async () => {
  const lost = {
    ...view,
    revision: 2,
    save_mode: 'ephemeral' as const,
    storage_state: 'ephemeral' as const,
    visible_fields: {},
    actions: [],
    state: 'failed_recoverable' as const,
    prompt_key: 'assistant.workflow.ephemeral_lost',
  };
  vi.mocked(workflowApi.list).mockResolvedValue([lost]);
  vi.mocked(workflowApi.view).mockResolvedValue(lost);
  vi.mocked(api.newConversation).mockResolvedValue({
    patient_id: 'DEMO-A',
    session_id: 'DEMO-fresh',
    demo_only: true,
    seeded_medication_count: 0,
    note: 'DEMO',
  });
  render(<AssistantScreen ownerId="DEMO-A" sessionId={null} onSession={vi.fn()} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Unfinished tasks' }));
  fireEvent.click(screen.getByRole('button', { name: 'Resume task: Unsaved task' }));
  await screen.findByText('Page details are unavailable. Please enter them again.');
  expect(screen.queryByText('Task progress saved.')).toBeNull();
  expect(workflowApi.originals).not.toHaveBeenCalled();
});

it('allows revocation during an upload and ignores a late saved response', async () => {
  let finish!: (value: Awaited<ReturnType<typeof workflowApi.uploadOriginal>>) => void;
  vi.mocked(workflowApi.uploadOriginal).mockReturnValue(
    new Promise((resolve) => {
      finish = resolve;
    }),
  );
  vi.mocked(workflowApi.view).mockResolvedValue({ ...view, revision: 2, state: 'outcome_unknown' });
  vi.mocked(workflowApi.event).mockResolvedValue({
    ...view,
    revision: 3,
    save_mode: 'ephemeral',
    storage_state: 'ephemeral',
  });
  await start();
  attach(new File(['DEMO bytes'], 'DEMO-original.png', { type: 'image/png' }));
  fireEvent.click(screen.getByRole('button', { name: 'Send' }));
  await waitFor(() => expect(workflowApi.uploadOriginal).toHaveBeenCalled());
  const revoke = screen.getByRole('button', { name: 'Do not save this workflow' });
  expect(revoke).not.toHaveProperty('disabled', true);
  fireEvent.click(revoke);
  await screen.findByText('Details stay on this page. Refreshing loses them.');
  await act(async () =>
    finish({
      attachment: {
        id: 'DEMO-original',
        task_id: view.task_id,
        original_checksum: 'DEMO-checksum',
        content_type: 'image/png',
        byte_size: 20,
        state: 'saved',
        extraction_status: 'failed',
        reason: 'provider_unavailable',
        cleanup_pending: false,
      },
      workflow: {
        ...view,
        revision: 2,
        state: 'failed_recoverable',
        prompt_key: 'assistant.enrollment.extraction_failed',
      },
    }),
  );
  expect(screen.queryByText('Task progress saved.')).toBeNull();
  expect(
    screen.queryByText(
      'The original photo is saved, but its medication details could not be read.',
    ),
  ).toBeNull();
  expect(workflowApi.event).toHaveBeenCalledWith(
    view.task_id,
    expect.objectContaining({ expected_revision: 2, kind: 'cancel_save' }),
    undefined,
  );
});

it('offers an explicit retry when allow-save fails after permission changed', async () => {
  vi.mocked(workflowApi.event)
    .mockResolvedValueOnce({
      ...view,
      revision: 2,
      save_mode: 'allowed',
      storage_state: 'save_failed',
      visible_fields: {},
      actions: [],
      prompt_key: 'assistant.workflow.save_failed',
    })
    .mockResolvedValueOnce({ ...view, revision: 3 });
  vi.mocked(workflowApi.uploadOriginal).mockResolvedValue({
    attachment: {
      id: 'DEMO-original',
      task_id: view.task_id,
      original_checksum: 'DEMO-checksum',
      content_type: 'image/png',
      byte_size: 20,
      state: 'saved',
      extraction_status: 'failed',
      reason: 'provider_unavailable',
      cleanup_pending: false,
    },
    workflow: {
      ...view,
      revision: 5,
      state: 'failed_recoverable',
      prompt_key: 'assistant.enrollment.extraction_failed',
    },
  });
  await start({ ...view, save_mode: 'ephemeral', storage_state: 'ephemeral' });
  attach(new File(['DEMO bytes'], 'DEMO-original.png', { type: 'image/png' }));
  fireEvent.click(screen.getByRole('button', { name: 'Save this medication and continue review' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Retry saving task' }));
  await screen.findByText(
    'The original photo is saved, but its medication details could not be read.',
  );
  expect(vi.mocked(workflowApi.event).mock.calls[1]![2]?.fields).toEqual({ method: 'photo' });
});

it('shows retained originals in the restored task and removes them on owner change', async () => {
  vi.mocked(workflowApi.originals).mockResolvedValue([
    {
      id: 'DEMO-original',
      task_id: view.task_id,
      original_checksum: 'DEMO-hash',
      content_type: 'image/png',
      byte_size: 20,
      state: 'saved',
      extraction_status: 'failed',
      reason: 'provider_unavailable',
      cleanup_pending: false,
    },
  ]);
  vi.mocked(workflowApi.sendMessage).mockResolvedValue({ reply, workflow: view, explanations: [] });
  const rendered = render(
    <AssistantScreen ownerId="DEMO-A" sessionId={null} onSession={vi.fn()} />,
  );
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Add a medication' } });
  fireEvent.click(screen.getByRole('button', { name: 'Send' }));
  await screen.findByRole('button', { name: 'View original 1' });
  rendered.rerender(<AssistantScreen ownerId="DEMO-B" sessionId={null} onSession={vi.fn()} />);
  expect(screen.queryByRole('button', { name: 'View original 1' })).toBeNull();
  expect(screen.queryByText('DEMO choose a source photo')).toBeNull();
});

it('clears page photos on owner change while an upload response is pending', async () => {
  let finish!: (value: Awaited<ReturnType<typeof workflowApi.uploadOriginal>>) => void;
  vi.mocked(workflowApi.uploadOriginal).mockReturnValue(
    new Promise((resolve) => {
      finish = resolve;
    }),
  );
  vi.mocked(workflowApi.sendMessage).mockResolvedValue({ reply, workflow: view, explanations: [] });
  const rendered = render(
    <AssistantScreen ownerId="DEMO-A" sessionId={null} onSession={vi.fn()} />,
  );
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Add a medication' } });
  fireEvent.click(screen.getByRole('button', { name: 'Send' }));
  await screen.findByText('DEMO choose a source photo');
  attach(new File(['DEMO private bytes'], 'DEMO-private.png', { type: 'image/png' }));
  fireEvent.click(screen.getByRole('button', { name: 'Send' }));
  await waitFor(() => expect(workflowApi.uploadOriginal).toHaveBeenCalled());
  rendered.rerender(<AssistantScreen ownerId="DEMO-B" sessionId={null} onSession={vi.fn()} />);
  await act(async () =>
    finish({
      attachment: {
        id: 'DEMO-original',
        task_id: view.task_id,
        original_checksum: 'DEMO-hash',
        content_type: 'image/png',
        byte_size: 20,
        state: 'saved',
        extraction_status: 'failed',
        reason: 'provider_unavailable',
        cleanup_pending: false,
      },
      workflow: { ...view, revision: 3 },
    }),
  );
  expect(screen.queryByText('DEMO-private.png')).toBeNull();
  expect(screen.queryByText('Task progress saved.')).toBeNull();
  expect(JSON.stringify(localStorage)).not.toContain('DEMO-private');
});

it('retries failed task listing and restores a task without resending the original request', async () => {
  vi.mocked(workflowApi.list)
    .mockRejectedValueOnce(new Error('DEMO list unavailable'))
    .mockResolvedValue([{ ...view, visible_fields: { medication_name: 'DEMO recovery' } }]);
  render(<AssistantScreen ownerId="DEMO-A" sessionId={null} onSession={vi.fn()} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Unfinished tasks' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Retry loading tasks' }));
  await screen.findByRole('button', { name: 'Resume task: DEMO recovery' });
  expect(workflowApi.sendMessage).not.toHaveBeenCalled();
});

it('preserves unsent form values while checking a lost no-save field response and retries with the current revision', async () => {
  const temporary = {
    ...view,
    save_mode: 'ephemeral' as const,
    storage_state: 'ephemeral' as const,
    visible_fields: { method: 'manual' },
    missing_fields: ['medication_name'],
    actions: [
      {
        kind: 'fields' as const,
        schema_id: 'medication.enroll:v1',
        field_names: ['medication_name'],
      },
    ],
  };
  vi.mocked(workflowApi.event)
    .mockRejectedValueOnce(new Error('DEMO field response lost'))
    .mockResolvedValueOnce({
      ...temporary,
      revision: 5,
      visible_fields: { method: 'manual', medication_name: 'DEMO retained input' },
    });
  vi.mocked(workflowApi.view).mockResolvedValue({
    ...temporary,
    revision: 4,
    visible_fields: {},
    prompt_key: 'assistant.workflow.ephemeral_lost',
  });
  vi.mocked(workflowApi.preview).mockResolvedValue({ ...temporary, revision: 4 });
  await start(temporary);
  const composer = screen.getByLabelText('Review your message before sending');
  fireEvent.change(composer, { target: { value: 'DEMO next question' } });
  fireEvent.change(screen.getByLabelText('Medication name'), {
    target: { value: 'DEMO retained input' },
  });
  expect(screen.getByRole('button', { name: 'Send' })).toHaveProperty('disabled', true);
  fireEvent.click(screen.getByRole('button', { name: 'Use these details' }));
  await screen.findByText('DEMO field response lost');
  fireEvent.click(screen.getByRole('button', { name: 'Dismiss' }));
  fireEvent.click(screen.getByRole('button', { name: 'Check task status' }));
  await waitFor(() => expect(workflowApi.preview).toHaveBeenCalled());
  await waitFor(() =>
    expect(screen.getByRole('button', { name: 'Use these details' })).not.toHaveProperty(
      'disabled',
      true,
    ),
  );
  expect(screen.getByLabelText('Medication name')).toHaveProperty('value', 'DEMO retained input');
  fireEvent.click(screen.getByRole('button', { name: 'Use these details' }));
  await waitFor(() =>
    expect(vi.mocked(workflowApi.event).mock.calls[1]![1].expected_revision).toBe(4),
  );
  expect(vi.mocked(workflowApi.event).mock.calls[1]![1].values.medication_name).toBe(
    'DEMO retained input',
  );
  await waitFor(() =>
    expect(screen.getByRole('button', { name: 'Send' })).not.toHaveProperty('disabled', true),
  );
  expect(composer).toHaveProperty('value', 'DEMO next question');
});
