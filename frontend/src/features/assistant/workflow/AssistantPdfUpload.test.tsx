// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { api } from '../../../api/client';
import { workflowApi, type WorkflowView } from '../../../api/assistantWorkflows';
import { AssistantWorkflow } from './AssistantWorkflow';
import { AssistantWorkflowOriginals } from './AssistantWorkflowOriginals';

vi.mock('../../../api/assistantWorkflows', async (load) => {
  const module = await load<typeof import('../../../api/assistantWorkflows')>();
  return { ...module, workflowApi: { ...module.workflowApi, uploadPdfOriginal: vi.fn() } };
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
const id = '00000000-0000-4000-8000-000000000099';
const source = '00000000-0000-4000-8000-000000000100';
const base: WorkflowView = {
  task_id: 'DEMO-pdf-task',
  revision: 1,
  capability_id: 'library.pdf.add',
  state: 'collecting',
  save_mode: 'allowed',
  storage_state: 'saved',
  prompt_key: 'assistant.pdf.collect',
  input_fields: {
    medication_id: id,
    filename: 'DEMO_original.pdf',
    category: 'prescription',
    description: 'DEMO document',
  },
  visible_fields: { medication_name: 'DEMO medicine' },
  missing_fields: ['source_pdf'],
  actions: [],
  explanations: [],
  result_ref: null,
};
const saved = {
  ...base,
  revision: 2,
  state: 'ready_for_review' as const,
  input_fields: { ...base.input_fields, source_attachment_id: source },
  missing_fields: [],
};
const ref = { kind: 'media_review' as const, id, version: 1 };
const reviewed: WorkflowView = {
  ...saved,
  revision: 3,
  state: 'awaiting_confirmation',
  prompt_key: 'assistant.pdf.review',
  actions: [
    {
      kind: 'existing_review',
      component_key: 'existing_media_management',
      owned_ref: ref,
      expected_version: 1,
    },
  ],
  result_ref: ref,
  visible_fields: { medication_name: 'DEMO medicine', upload_attempted: false },
};
const file = new File(['%PDF-1.7\n% DEMO_ONLY\n%%EOF'], 'DEMO_original.pdf', {
  type: 'application/pdf',
});
const attachment = {
  id: source,
  task_id: base.task_id,
  original_checksum: 'a'.repeat(64),
  content_type: 'application/pdf' as const,
  byte_size: file.size,
  state: 'saved' as const,
  extraction_status: 'not_requested' as const,
  reason: null,
  cleanup_pending: false,
};

async function pick() {
  fireEvent.change(await screen.findByLabelText('Choose a PDF file'), {
    target: { files: [file] },
  });
}

it('can reopen independent review after an unchanged read proves registration is still pending', async () => {
  vi.spyOn(workflowApi, 'originalBlob').mockResolvedValue(file);
  const write = vi
    .spyOn(api, 'uploadLibraryPdf')
    .mockRejectedValue(new Error('DEMO registration unavailable'));
  const send = vi.fn().mockResolvedValue(reviewed);
  render(<AssistantWorkflow view={reviewed} busy={false} onEvent={send} onView={vi.fn()} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Review PDF upload' }));
  fireEvent.click(screen.getByRole('checkbox'));
  fireEvent.click(screen.getByRole('button', { name: 'Add PDF to library' }));
  expect(await screen.findByRole('alert')).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Check PDF result' }));
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  fireEvent.click(screen.getByRole('button', { name: 'Review PDF upload' }));
  expect(screen.getByRole('button', { name: 'Add PDF to library' })).toHaveProperty(
    'disabled',
    false,
  );
  expect(write).toHaveBeenCalledTimes(1);
});

it('keeps the chosen PDF page-only across explicit save preference without a native write', async () => {
  const native = vi.spyOn(api, 'uploadLibraryPdf');
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
  fireEvent.click(await screen.findByRole('button', { name: 'Apply PDF details' }));
  await waitFor(() =>
    expect(send).toHaveBeenCalledWith(
      expect.objectContaining({
        kind: 'provide_fields',
        values: {
          filename: 'DEMO_original.pdf',
          category: 'prescription',
          description: 'DEMO document',
        },
      }),
    ),
  );
  fireEvent.click(screen.getByRole('button', { name: 'Save PDF draft' }));
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
  expect(workflowApi.uploadPdfOriginal).not.toHaveBeenCalled();
  expect(native).not.toHaveBeenCalled();
});

it('retains the selected PDF and fields after original save fails', async () => {
  vi.mocked(workflowApi.uploadPdfOriginal).mockRejectedValue(new Error('DEMO storage unavailable'));
  render(
    <AssistantWorkflow
      view={base}
      busy={false}
      onEvent={vi.fn().mockResolvedValue({ ...base, revision: 2 })}
      onView={vi.fn()}
    />,
  );
  await pick();
  fireEvent.click(await screen.findByRole('button', { name: 'Save original PDF' }));
  expect(await screen.findByRole('alert')).toBeTruthy();
  expect(screen.getByText(file.name)).toBeTruthy();
  expect(screen.getByLabelText('Description (optional)')).toHaveProperty('value', 'DEMO document');
});

it('stores only the original and uses a fresh nonce after saving is revoked then enabled', async () => {
  vi.mocked(workflowApi.uploadPdfOriginal)
    .mockClear()
    .mockResolvedValue({ workflow: saved, attachment });
  const native = vi.spyOn(api, 'uploadLibraryPdf');
  const onView = vi.fn();
  const mounted = render(
    <AssistantWorkflow view={base} busy={false} onEvent={vi.fn()} onView={onView} />,
  );
  await pick();
  fireEvent.click(await screen.findByRole('button', { name: 'Save original PDF' }));
  await waitFor(() => expect(onView).toHaveBeenCalledWith(saved));
  await waitFor(() =>
    expect(screen.getByRole('button', { name: 'Apply PDF details' })).toHaveProperty(
      'disabled',
      false,
    ),
  );
  mounted.rerender(
    <AssistantWorkflow
      view={{ ...base, revision: 3, save_mode: 'ephemeral', storage_state: 'ephemeral' }}
      busy={false}
      onEvent={vi.fn()}
      onView={onView}
    />,
  );
  mounted.rerender(
    <AssistantWorkflow
      view={{ ...base, revision: 4 }}
      busy={false}
      onEvent={vi.fn()}
      onView={onView}
    />,
  );
  fireEvent.click(await screen.findByRole('button', { name: 'Save original PDF' }));
  await waitFor(() => expect(workflowApi.uploadPdfOriginal).toHaveBeenCalledTimes(2));
  const calls = vi.mocked(workflowApi.uploadPdfOriginal).mock.calls;
  expect(calls[1]![1]).not.toBe(calls[0]![1]);
  expect(native).not.toHaveBeenCalled();
});

it('loads the saved PDF only after independent private-storage confirmation and preserves filename', async () => {
  const native = vi
    .spyOn(api, 'uploadLibraryPdf')
    .mockResolvedValue({ file: { id }, duplicate: false } as never);
  const blob = vi
    .spyOn(workflowApi, 'originalBlob')
    .mockResolvedValue(new Blob(['%PDF-1.7\n% DEMO_ONLY\n%%EOF'], { type: 'application/pdf' }));
  render(
    <AssistantWorkflow
      view={reviewed}
      busy={false}
      onEvent={vi.fn().mockResolvedValue({ ...reviewed, revision: 4, state: 'completed' })}
      onView={vi.fn()}
    />,
  );
  fireEvent.click(await screen.findByRole('button', { name: 'Review PDF upload' }));
  expect(native).not.toHaveBeenCalled();
  expect(blob).not.toHaveBeenCalled();
  expect(screen.getByRole('dialog').textContent).toContain('DEMO_original.pdf');
  expect(screen.getByRole('button', { name: 'Add PDF to library' })).toHaveProperty(
    'disabled',
    true,
  );
  fireEvent.click(screen.getByRole('checkbox'));
  fireEvent.click(screen.getByRole('button', { name: 'Add PDF to library' }));
  await waitFor(() =>
    expect(native).toHaveBeenCalledWith(
      id,
      expect.objectContaining({ name: 'DEMO_original.pdf', type: 'application/pdf' }),
      'prescription',
      'DEMO document',
      { task_id: base.task_id, expected_revision: 3 },
    ),
  );
});

it('requires result checking after an uncertain native PDF upload', async () => {
  vi.spyOn(api, 'uploadLibraryPdf').mockRejectedValue(new Error('DEMO response lost'));
  vi.spyOn(workflowApi, 'originalBlob').mockResolvedValue(
    new Blob(['DEMO original'], { type: 'application/pdf' }),
  );
  const send = vi.fn().mockResolvedValue({ ...reviewed, revision: 4, state: 'completed' });
  render(<AssistantWorkflow view={reviewed} busy={false} onEvent={send} onView={vi.fn()} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Review PDF upload' }));
  fireEvent.click(screen.getByRole('checkbox'));
  fireEvent.click(screen.getByRole('button', { name: 'Add PDF to library' }));
  expect(await screen.findByRole('alert')).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Add PDF to library' })).toHaveProperty(
    'disabled',
    true,
  );
  fireEvent.click(screen.getByRole('button', { name: 'Check PDF result' }));
  await waitFor(() =>
    expect(send).toHaveBeenCalledWith(expect.objectContaining({ kind: 'report_business_result' })),
  );
});

it('shows PDF originals as documents without image decoding or recognition controls', async () => {
  vi.spyOn(workflowApi, 'originals').mockResolvedValue([attachment]);
  vi.spyOn(workflowApi, 'originalBlob').mockResolvedValue(
    new Blob(['DEMO PDF'], { type: 'application/pdf' }),
  );
  vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:DEMO-pdf');
  vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
  render(
    <AssistantWorkflowOriginals
      view={saved}
      files={[]}
      busy={false}
      consent
      onConsent={vi.fn()}
      onView={vi.fn()}
    />,
  );
  fireEvent.click(await screen.findByRole('button', { name: 'View original PDF 1' }));
  const download = await screen.findByRole('link', { name: 'Download original PDF' });
  expect(download.getAttribute('href')).toBe('blob:DEMO-pdf');
  expect(screen.getByRole('link', { name: 'Open original PDF' }).getAttribute('rel')).toBe(
    'noopener noreferrer',
  );
  expect(document.querySelector('iframe')).toBeNull();
  expect(screen.queryByRole('img')).toBeNull();
  expect(screen.queryByRole('checkbox')).toBeNull();
});
