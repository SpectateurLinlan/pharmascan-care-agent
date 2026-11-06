// @vitest-environment jsdom
import { readFileSync } from 'node:fs';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { fireEvent, waitFor } from '@testing-library/react';

vi.mock('./App', async () => {
  const { createElement } = await import('react');
  return {
    App: ({ initialDraft }: { initialDraft: { text: string } }) =>
      createElement('input', { id: 'DEMO-react-input', defaultValue: initialDraft.text }),
  };
});

beforeEach(() => {
  const html = readFileSync('index.html', 'utf8');
  const parsed = new DOMParser().parseFromString(html, 'text/html');
  document.body.innerHTML = parsed.body.innerHTML;
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
    callback(0);
    return 1;
  });
});
afterEach(() => {
  document.body.innerHTML = '';
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const root = () => document.getElementById('root')!;
const input = () => document.querySelector<HTMLInputElement>('#startup-message')!;

it('commits the DOM handover synchronously so input events cannot land between snapshot and replacement', async () => {
  const { mountApplication } = await import('./mountApplication');
  input().value = 'DEMO before handover';
  mountApplication(root(), {
    text: 'DEMO live handover',
    focused: false,
    selection: { start: 0, end: 0 },
  });
  expect(document.querySelector<HTMLInputElement>('#DEMO-react-input')?.value).toBe(
    'DEMO live handover',
  );
  expect(input()).toBeNull();
});

it('ships a nonclinical shell and disabled send before any JavaScript runs', () => {
  expect(document.querySelector('#startup-shell')).not.toBeNull();
  expect(input()).not.toBeNull();
  expect(document.querySelector<HTMLButtonElement>('.composer-send')?.disabled).toBe(true);
  expect(root().textContent).toContain('MediThread');
  expect(root().textContent).not.toContain('0 medicines');
});

it('hands over the current local text, focus and selection exactly once', async () => {
  const persist = vi.spyOn(Storage.prototype, 'setItem');
  const { startApplication } = await import('./bootstrap');
  const mountApplication = vi.fn();
  let resolve!: (module: { mountApplication: typeof mountApplication }) => void;
  const loading = new Promise<{ mountApplication: typeof mountApplication }>((done) => {
    resolve = done;
  });
  // Typing can precede attachment of the lightweight entry's listeners.
  input().value = 'DEMO before listeners';
  startApplication(root(), () => loading);
  input().focus();
  fireEvent.input(input(), { target: { value: 'DEMO final draft' } });
  input().setSelectionRange(2, 7);
  fireEvent.keyDown(input(), { key: 'Enter' });
  expect(mountApplication).not.toHaveBeenCalled();
  resolve({ mountApplication });
  await waitFor(() => expect(mountApplication).toHaveBeenCalledOnce());
  expect(mountApplication).toHaveBeenCalledWith(root(), {
    text: 'DEMO final draft',
    focused: true,
    selection: { start: 2, end: 7 },
  });
  expect(persist).not.toHaveBeenCalled();
});

it('waits for composition end and does not steal focus from another control', async () => {
  const { startApplication } = await import('./bootstrap');
  const mountApplication = vi.fn();
  let resolve!: (module: { mountApplication: typeof mountApplication }) => void;
  const loading = new Promise<{ mountApplication: typeof mountApplication }>((done) => {
    resolve = done;
  });
  input().dataset.composing = 'true';
  startApplication(root(), () => loading);
  input().focus();
  fireEvent.compositionStart(input());
  fireEvent.input(input(), { target: { value: '布洛' } });
  resolve({ mountApplication });
  await Promise.resolve();
  expect(mountApplication).not.toHaveBeenCalled();
  fireEvent.input(input(), { target: { value: '布洛芬' } });
  const other = document.createElement('button');
  document.body.append(other);
  other.focus();
  fireEvent.compositionEnd(input());
  await waitFor(() => expect(mountApplication).toHaveBeenCalledOnce());
  expect(mountApplication.mock.calls[0]?.[1]).toMatchObject({ text: '布洛芬', focused: false });
});

it('keeps input editable after a failed download and retries without clearing it', async () => {
  const { startApplication } = await import('./bootstrap');
  const mountApplication = vi.fn();
  const load = vi
    .fn()
    .mockRejectedValueOnce(new Error('DEMO failed asset'))
    .mockResolvedValueOnce({ mountApplication });
  startApplication(root(), load);
  fireEvent.input(input(), { target: { value: 'DEMO retained on failure' } });
  const retry = document.querySelector<HTMLButtonElement>('#startup-retry')!;
  await waitFor(() => expect(retry.hidden).toBe(false));
  expect(document.querySelector('[role="alert"]')?.textContent).toContain('could not');
  expect(input().value).toBe('DEMO retained on failure');
  fireEvent.click(retry);
  fireEvent.click(retry);
  await waitFor(() => expect(mountApplication).toHaveBeenCalledOnce());
  expect(load).toHaveBeenCalledTimes(2);
  expect(mountApplication.mock.calls[0]?.[1]?.text).toBe('DEMO retained on failure');
});
