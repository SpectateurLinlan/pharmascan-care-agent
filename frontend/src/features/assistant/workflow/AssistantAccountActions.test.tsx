// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { accountAuth, type Account } from '../../../api/auth';
import type { WorkflowView } from '../../../api/assistantWorkflows';
import { AssistantWorkflow } from './AssistantWorkflow';

const agentEvents = vi.hoisted(() => vi.fn());

function AssistantAccountActions({
  view,
  busy,
  onIdentityChanged,
}: {
  view: WorkflowView;
  busy: boolean;
  onIdentityChanged?: () => void;
}) {
  return (
    <AssistantWorkflow
      view={view}
      busy={busy}
      onEvent={agentEvents}
      onAccountIdentityChanged={onIdentityChanged}
    />
  );
}

vi.mock('../../../api/auth', () => ({
  accountAuth: {
    available: true,
    account: vi.fn(),
    requestEmail: vi.fn(),
    verifyEmail: vi.fn(),
    passwordLogin: vi.fn(),
    setPassword: vi.fn(),
    signOut: vi.fn(),
  },
}));
vi.mock('../../reminders/webPush', () => ({
  disableWebPush: vi.fn().mockResolvedValue(undefined),
}));
const base: WorkflowView = {
  task_id: 'DEMO-secure-account',
  revision: 1,
  capability_id: 'account.status',
  state: 'collecting',
  save_mode: 'allowed',
  storage_state: 'saved',
  prompt_key: 'assistant.account.secure',
  input_fields: {},
  visible_fields: {},
  missing_fields: [],
  actions: [{ kind: 'secure_account', action: 'status' }],
  explanations: [],
  result_ref: null,
};
beforeEach(() => {
  vi.spyOn(globalThis, 'fetch').mockRejectedValue(new Error('Unexpected backend request'));
  vi.mocked(accountAuth.account).mockResolvedValue({ kind: 'guest', email: null, verified: false });
});
afterEach(() => {
  expect(agentEvents).not.toHaveBeenCalled();
  expect(fetch).not.toHaveBeenCalled();
  cleanup();
  vi.restoreAllMocks();
  vi.clearAllMocks();
});

async function open(action: string, identity = vi.fn()) {
  render(
    <AssistantAccountActions
      view={{ ...base, capability_id: `account.${action}` }}
      busy={false}
      onIdentityChanged={identity}
    />,
  );
  fireEvent.click(await screen.findByRole('button', { name: 'Open secure account form' }));
  await waitFor(() => expect(screen.queryByText('Loading account...')).toBeNull());
  return identity;
}

it('reads account status only after opening the secure form', async () => {
  render(<AssistantAccountActions view={base} busy={false} />);
  expect(accountAuth.account).not.toHaveBeenCalled();
  fireEvent.click(await screen.findByRole('button', { name: 'Open secure account form' }));
  await screen.findByText('Link email and keep my records', { selector: 'h3' });
  expect(accountAuth.account).toHaveBeenCalledOnce();
});
it('sends login secrets only to the original AccountPort and clears them after submission', async () => {
  const identity = await open('login');
  fireEvent.change(await screen.findByLabelText('Email'), {
    target: { value: 'demo@example.invalid' },
  });
  fireEvent.change(screen.getByLabelText('Password'), {
    target: { value: 'DEMO-password-secret' },
  });
  const signIn = screen.getByRole('button', { name: 'Sign in' });
  expect(signIn).toHaveProperty('disabled', true);
  fireEvent.click(screen.getByRole('checkbox'));
  fireEvent.click(signIn);
  await waitFor(() =>
    expect(accountAuth.passwordLogin).toHaveBeenCalledWith(
      'demo@example.invalid',
      'DEMO-password-secret',
    ),
  );
  await waitFor(() => expect(identity).toHaveBeenCalledOnce());
  expect(screen.getByLabelText('Password')).toHaveProperty('value', '');
  expect(screen.queryByText('DEMO-password-secret')).toBeNull();
});
it('uses native email link and OTP flows without an Agent input field', async () => {
  const identity = await open('link');
  fireEvent.change(await screen.findByLabelText('Email'), {
    target: { value: 'demo@example.invalid' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Email code / Magic Link' }));
  await waitFor(() =>
    expect(accountAuth.requestEmail).toHaveBeenCalledWith('demo@example.invalid', 'link'),
  );
  fireEvent.change(await screen.findByLabelText('Email code'), { target: { value: '123456' } });
  fireEvent.click(screen.getByRole('button', { name: 'Verify and continue' }));
  await waitFor(() =>
    expect(accountAuth.verifyEmail).toHaveBeenCalledWith('demo@example.invalid', '123456', 'link'),
  );
  await waitFor(() => expect(identity).toHaveBeenCalledOnce());
});
it('opens the native verified-member password form without automatically changing it', async () => {
  vi.mocked(accountAuth.account).mockResolvedValue({
    kind: 'member',
    email: 'demo@example.invalid',
    verified: true,
  });
  await open('password');
  fireEvent.change(await screen.findByLabelText(/New password/), {
    target: { value: 'DEMO-new-password-secret' },
  });
  expect(accountAuth.setPassword).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Save password' }));
  await waitFor(() =>
    expect(accountAuth.setPassword).toHaveBeenCalledWith('DEMO-new-password-secret'),
  );
  await waitFor(() => expect(screen.queryByLabelText(/New password/)).toBeNull());
});
it('requires native signout confirmation and owner reset', async () => {
  vi.mocked(accountAuth.account).mockResolvedValue({
    kind: 'member',
    email: 'demo@example.invalid',
    verified: true,
  });
  const identity = await open('signout');
  const dialog = await screen.findByRole('dialog', { name: 'Sign out?' });
  expect(accountAuth.signOut).not.toHaveBeenCalled();
  fireEvent.click(within(dialog).getByRole('button', { name: 'Sign out' }));
  await waitFor(() => expect(accountAuth.signOut).toHaveBeenCalledOnce());
  await waitFor(() => expect(identity).toHaveBeenCalledOnce());
});
it('unmounts native credentials on close and reports local Auth limitations honestly', async () => {
  await open('login');
  fireEvent.change(await screen.findByLabelText('Email'), {
    target: { value: 'demo@example.invalid' },
  });
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'DEMO-cancel-secret' } });
  fireEvent.click(screen.getByRole('button', { name: 'Close account form' }));
  expect(screen.queryByLabelText('Password')).toBeNull();
  expect(accountAuth.passwordLogin).not.toHaveBeenCalled();
  vi.mocked(accountAuth.account).mockResolvedValue({
    kind: 'local',
    email: null,
    verified: false,
  } as Account);
  fireEvent.click(await screen.findByRole('button', { name: 'Open secure account form' }));
  expect(
    await screen.findByText(
      'Email sign-in and account linking are unavailable in this local demo. No authenticated account is connected here.',
    ),
  ).toBeTruthy();
});
