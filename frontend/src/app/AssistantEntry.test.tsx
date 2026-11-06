// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { AssistantEntry } from './AssistantEntry';

const mounted = vi.hoisted(() => vi.fn());
vi.mock('../features/assistant/conversation/AssistantScreen', () => ({
  AssistantScreen: (props: { initialText?: string }) => {
    mounted(props);
    return <input aria-label="Connected message" defaultValue={props.initialText} />;
  },
}));
afterEach(() => {
  cleanup();
  mounted.mockClear();
});

it('restores the lightweight startup draft and caret while the connection is pending', () => {
  const props = {
    sessionId: null,
    onSession: vi.fn(),
    connectionReady: false,
    onRetryConnection: vi.fn(),
    startupDraft: { text: 'DEMO early draft', focused: true, selection: { start: 2, end: 6 } },
  };
  const view = render(<AssistantEntry {...props} />);
  const input = screen.getByRole('textbox') as HTMLInputElement;
  expect(input.value).toBe('DEMO early draft');
  expect(document.activeElement).toBe(input);
  expect([input.selectionStart, input.selectionEnd]).toEqual([2, 6]);
  view.rerender(
    <AssistantEntry {...props} sessionId="DEMO-session" ownerId="DEMO-owner" connectionReady />,
  );
  expect(mounted.mock.calls.at(-1)![0].initialSelection).toEqual({ start: 2, end: 6 });
});

it('keeps startup text local and does not mount chat effects until verified readiness', () => {
  const props = {
    sessionId: null,
    onSession: vi.fn(),
    connectionReady: false,
    onRetryConnection: vi.fn(),
  };
  const view = render(<AssistantEntry {...props} />);
  const input = screen.getByRole('textbox');
  fireEvent.change(input, { target: { value: 'DEMO typed before connection' } });
  fireEvent.keyDown(input, { key: 'Enter' });
  expect(screen.getByRole('button', { name: 'Send' })).toHaveProperty('disabled', true);
  expect(screen.getByRole('button', { name: 'Send' }).textContent).toBe('Send');
  expect(mounted).not.toHaveBeenCalled();
  view.rerender(<AssistantEntry {...props} sessionId="DEMO-session" ownerId="DEMO-owner" />);
  expect(mounted).not.toHaveBeenCalled();
  view.rerender(
    <AssistantEntry {...props} sessionId="DEMO-session" ownerId="DEMO-owner" connectionReady />,
  );
  expect(screen.getByRole('textbox')).toHaveProperty('value', 'DEMO typed before connection');
});

it('keeps text across a connection failure and explicit retry', () => {
  const retry = vi.fn();
  const props = {
    sessionId: null,
    onSession: vi.fn(),
    connectionReady: false,
    onRetryConnection: retry,
  };
  const view = render(<AssistantEntry {...props} />);
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'DEMO retained question' } });
  view.rerender(
    <AssistantEntry {...props} connectionError={new Error('DEMO connection failed')} />,
  );
  fireEvent.click(screen.getByRole('button', { name: 'Retry connecting' }));
  expect(retry).toHaveBeenCalledOnce();
  expect(screen.getByRole('textbox')).toHaveProperty('value', 'DEMO retained question');
  expect(mounted).not.toHaveBeenCalled();
});

it.each([true, false])(
  'hands focus/caret over only when the pending input is focused (%s)',
  (focused) => {
    const props = {
      sessionId: null,
      onSession: vi.fn(),
      connectionReady: false,
      onRetryConnection: vi.fn(),
    };
    const view = render(<AssistantEntry {...props} />);
    const input = screen.getByRole('textbox') as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'DEMO caret handoff' } });
    input.setSelectionRange(3, 8);
    fireEvent.select(input);
    if (focused) fireEvent.focus(input);
    else {
      fireEvent.focus(input);
      fireEvent.blur(input);
    }
    view.rerender(
      <AssistantEntry {...props} sessionId="DEMO-session" ownerId="DEMO-owner" connectionReady />,
    );
    const options = mounted.mock.calls.at(-1)![0];
    expect(options.initialSelection).toEqual(focused ? { start: 3, end: 8 } : undefined);
  },
);

it('finishes IME composition before replacing the pending composer', () => {
  const props = {
    sessionId: null,
    onSession: vi.fn(),
    connectionReady: false,
    onRetryConnection: vi.fn(),
  };
  const view = render(<AssistantEntry {...props} />);
  const input = screen.getByRole('textbox');
  fireEvent.compositionStart(input);
  fireEvent.change(input, { target: { value: '布洛' } });
  view.rerender(
    <AssistantEntry {...props} sessionId="DEMO-session" ownerId="DEMO-owner" connectionReady />,
  );
  expect(mounted).not.toHaveBeenCalled();
  fireEvent.change(input, { target: { value: '布洛芬' } });
  fireEvent.compositionEnd(input, { data: '芬' });
  expect(screen.getByRole('textbox')).toHaveProperty('value', '布洛芬');
});
