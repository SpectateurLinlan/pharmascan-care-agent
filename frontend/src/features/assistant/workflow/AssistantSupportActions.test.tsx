// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { api } from '../../../api/client';
import type { WorkflowView } from '../../../api/assistantWorkflows';
import { AssistantWorkflow } from './AssistantWorkflow';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
const base: WorkflowView = {
  task_id: 'DEMO-support',
  revision: 1,
  capability_id: 'conversation.new',
  state: 'collecting',
  save_mode: 'allowed',
  storage_state: 'saved',
  prompt_key: 'assistant.conversation.patient_action',
  input_fields: {},
  visible_fields: {},
  missing_fields: [],
  actions: [{ kind: 'conversation', action: 'new', conversation_id: null }],
  explanations: [],
  result_ref: null,
};
it('confirms once then adopts the actual native session without a second creation', async () => {
  const native = vi
    .spyOn(api, 'newConversation')
    .mockResolvedValue({ session_id: 'DEMO-fresh' } as never);
  const adopt = vi.fn();
  render(
    <AssistantWorkflow
      view={base}
      busy={false}
      onEvent={vi.fn()}
      clientActions={{ adoptNew: adopt }}
    />,
  );
  fireEvent.click(await screen.findByRole('button', { name: 'Start a new conversation' }));
  expect(native).not.toHaveBeenCalled();
  fireEvent.click(
    within(screen.getByRole('dialog')).getByRole('button', { name: 'Confirm conversation action' }),
  );
  await waitFor(() => expect(adopt).toHaveBeenCalledWith({ session_id: 'DEMO-fresh' }));
  expect(native).toHaveBeenCalledTimes(1);
  expect(native).toHaveBeenCalledWith({ task_id: base.task_id, expected_revision: 1 });
});
it('clears through the native confirmed API then resets history views without cancelling drafts', async () => {
  const native = vi.spyOn(api, 'clearConversationHistory').mockResolvedValue({ cleared: true });
  const cleared = vi.fn();
  const event = vi.fn();
  render(
    <AssistantWorkflow
      view={{
        ...base,
        capability_id: 'conversation.clear',
        actions: [{ kind: 'conversation', action: 'clear', conversation_id: null }],
      }}
      busy={false}
      onEvent={event}
      clientActions={{ cleared }}
    />,
  );
  fireEvent.click(await screen.findByRole('button', { name: 'Clear chat history' }));
  expect(native).not.toHaveBeenCalled();
  expect(screen.getByRole('dialog').textContent).toContain(
    'Saved workflow drafts and medication records are retained.',
  );
  fireEvent.click(screen.getByRole('button', { name: 'Confirm conversation action' }));
  await waitFor(() => expect(cleared).toHaveBeenCalledOnce());
  expect(event).not.toHaveBeenCalled();
});
it('keeps navigation explicit and rejects untrusted destinations and extra query keys', async () => {
  const navigate = vi.fn();
  const view = {
    ...base,
    capability_id: 'navigation.open',
    actions: [{ kind: 'navigate' as const, route: 'today' as const }],
    visible_fields: { navigation_query: { patient_id: 'DEMO-untrusted' } },
  };
  const { rerender } = render(
    <AssistantWorkflow view={view} busy={false} onEvent={vi.fn()} clientActions={{ navigate }} />,
  );
  expect(navigate).not.toHaveBeenCalled();
  fireEvent.click(await screen.findByRole('button', { name: 'Open page' }));
  expect(navigate).not.toHaveBeenCalled();
  rerender(
    <AssistantWorkflow
      view={{ ...view, visible_fields: { navigation_query: {} } }}
      busy={false}
      onEvent={vi.fn()}
      clientActions={{ navigate }}
    />,
  );
  fireEvent.click(await screen.findByRole('button', { name: 'Open page' }));
  expect(navigate).toHaveBeenCalledWith('today', {});
});
it('plays only page text after an explicit click and provides a stop control', async () => {
  const play = vi.fn().mockResolvedValue(undefined);
  const stop = vi.fn();
  render(
    <AssistantWorkflow
      view={{
        ...base,
        capability_id: 'speech.playback',
        actions: [{ kind: 'device', action: 'speech_playback' }],
      }}
      busy={false}
      onEvent={vi.fn()}
      clientActions={{ play, stop, voiceEnabled: true }}
    />,
  );
  expect(play).not.toHaveBeenCalled();
  fireEvent.change(await screen.findByLabelText('Text to read'), {
    target: { value: 'DEMO local reading' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Read text aloud' }));
  await waitFor(() => expect(play).toHaveBeenCalledWith('DEMO local reading'));
  fireEvent.click(screen.getByRole('button', { name: 'Stop audio' }));
  expect(stop).toHaveBeenCalled();
});
it('submits feedback only after independent review and retains the draft on native failure', async () => {
  const native = vi.spyOn(api, 'feedback').mockRejectedValue(new Error('DEMO offline'));
  const event = vi.fn();
  const view: WorkflowView = {
    ...base,
    capability_id: 'feedback.submit',
    state: 'awaiting_confirmation',
    actions: [],
    result_ref: { kind: 'settings_review', id: 'DEMO-feedback', version: 1 },
    visible_fields: {
      settings_review: {
        payload: { id: 'DEMO-feedback', category: 'issue', message: 'DEMO useful issue' },
      },
    },
  };
  render(<AssistantWorkflow view={view} busy={false} onEvent={event} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Review feedback' }));
  expect(native).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Confirm feedback save' }));
  await screen.findByRole('alert');
  expect(screen.getByRole('dialog').textContent).toContain('DEMO useful issue');
  expect(event).not.toHaveBeenCalled();
});
it('lets the patient edit feedback after a checked unchanged native result', async () => {
  const event = vi.fn();
  const view: WorkflowView = {
    ...base,
    capability_id: 'feedback.submit',
    state: 'awaiting_confirmation',
    input_fields: { category: 'issue', message: 'DEMO retained description' },
    actions: [],
    result_ref: { kind: 'settings_review', id: 'DEMO-feedback', version: 1 },
    visible_fields: {
      settings_review: {
        payload: { id: 'DEMO-feedback', category: 'issue', message: 'DEMO retained description' },
      },
    },
  };
  render(<AssistantWorkflow view={view} busy={false} onEvent={event} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Edit feedback details' }));
  fireEvent.change(screen.getByLabelText('Description'), {
    target: { value: 'DEMO corrected description' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Apply feedback details' }));
  await waitFor(() =>
    expect(event).toHaveBeenCalledWith(
      expect.objectContaining({
        kind: 'provide_fields',
        values: { category: 'issue', message: 'DEMO corrected description' },
      }),
    ),
  );
});
it('explains no-save support and feedback tasks without medication-plan instructions', async () => {
  const { rerender } = render(
    <AssistantWorkflow
      view={{ ...base, save_mode: 'ephemeral', storage_state: 'ephemeral' }}
      busy={false}
      onEvent={vi.fn()}
    />,
  );
  expect(screen.queryByText(/The plan still needs review/)).toBeNull();
  rerender(
    <AssistantWorkflow
      view={{
        ...base,
        capability_id: 'feedback.submit',
        save_mode: 'ephemeral',
        storage_state: 'ephemeral',
        actions: [],
      }}
      busy={false}
      onEvent={vi.fn()}
    />,
  );
  expect(screen.queryByText(/The plan still needs review/)).toBeNull();
  await screen.findByRole('button', { name: 'Apply feedback details' });
});
