// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { AssistantProgress } from './AssistantProgress';

afterEach(cleanup);
it.each(['en', 'zh'] as const)(
  'keeps %s recovery guidance for a worker interruption',
  (language) => {
    const check = vi.fn();
    render(
      <AssistantProgress
        language={language}
        status="failed"
        event={{
          sequence: 3,
          run_id: 'DEMO',
          kind: 'run_failed',
          action_key: null,
          status: 'failed',
          reason_key: 'worker_interrupted',
        }}
        stopping={false}
        onStop={() => {}}
        onCheck={check}
      />,
    );
    expect(screen.getByRole('status').textContent).toContain(
      language === 'en' ? 'Check conversation history or saved drafts' : '核对对话或已保存草稿',
    );
    fireEvent.click(
      screen.getByRole('button', {
        name: language === 'en' ? 'Check processing status' : '查看处理状态',
      }),
    );
    expect(check).toHaveBeenCalledOnce();
    expect(
      screen.queryByRole('button', { name: language === 'en' ? 'Stop processing' : '停止处理' }),
    ).toBeNull();
  },
);
it.each(['en', 'zh'] as const)(
  'shows actual %s phase with stop and no fake percentage',
  (language) => {
    const onStop = vi.fn();
    render(
      <AssistantProgress
        language={language}
        status="running"
        event={{
          sequence: 2,
          run_id: 'DEMO',
          kind: 'step_started',
          action_key: 'tool',
          status: 'running',
        }}
        stopping={false}
        onStop={onStop}
        onCheck={() => {}}
      />,
    );
    expect(screen.getByRole('status').textContent).toContain(
      language === 'en' ? 'Checking application records' : '正在查询应用记录',
    );
    fireEvent.click(
      screen.getByRole('button', { name: language === 'en' ? 'Stop processing' : '停止处理' }),
    );
    expect(onStop).toHaveBeenCalledOnce();
    expect(document.body.textContent).not.toContain('%');
  },
);
it('explains cooperative stopping and preserves completed changes', () => {
  render(
    <AssistantProgress
      language="en"
      status="cancelling"
      event={null}
      stopping
      onStop={() => {}}
      onCheck={() => {}}
    />,
  );
  expect(screen.getByRole('status').textContent).toContain(
    'Waiting for the current step to finish',
  );
  expect((screen.getByRole('button') as HTMLButtonElement).disabled).toBe(true);
});
it('offers only a status check for an unknown result', () => {
  const check = vi.fn();
  render(
    <AssistantProgress
      language="zh"
      status="unknown"
      event={null}
      stopping={false}
      onStop={() => {}}
      onCheck={check}
    />,
  );
  fireEvent.click(screen.getByRole('button', { name: '查看处理状态' }));
  expect(check).toHaveBeenCalledOnce();
  expect(screen.getByRole('status').textContent).toContain('核对对话或已保存草稿');
});
