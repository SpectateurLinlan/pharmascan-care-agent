import type { RunProgress, RunStatus } from '../../../api/assistantWorkflows';

export function AssistantProgress({
  language,
  status,
  event,
  stopping,
  onStop,
  onCheck,
}: {
  language: 'en' | 'zh';
  status: RunStatus | 'connecting' | 'unknown';
  event: RunProgress | null;
  stopping: boolean;
  onStop: () => void;
  onCheck: () => void;
}) {
  const zh = language === 'zh';
  const waiting = stopping || status === 'cancelling';
  const text = waiting
    ? zh
      ? '正在停止；等待当前步骤结束。已完成的更改会保留。'
      : 'Stopping. Waiting for the current step to finish. Completed changes remain saved.'
    : status === 'connecting'
      ? zh
        ? '正在连接处理服务…'
        : 'Connecting to the assistant…'
      : status === 'running'
        ? event?.action_key === 'model'
          ? zh
            ? '正在整理已核实的资料…'
            : 'Preparing an answer from verified information…'
          : event?.action_key === 'tool'
            ? zh
              ? '正在查询应用记录或准备核对步骤…'
              : 'Checking application records or preparing a review…'
            : zh
              ? '正在处理您的请求…'
              : 'Processing your request…'
        : status === 'cancelled'
          ? zh
            ? '处理已停止，已完成的更改会保留。'
            : 'Processing stopped. Completed changes remain saved.'
          : status === 'completed'
            ? zh
              ? '处理已完成。如未收到回答，请先核对对话或已保存草稿。'
              : 'Processing completed. If the answer did not arrive, check conversation history or saved drafts.'
            : status === 'failed'
              ? zh
                ? '处理未完成，请先核对对话或已保存草稿；输入仍保留。'
                : 'Processing did not finish. Check conversation history or saved drafts; your input is retained.'
              : zh
                ? '连接已中断，请先核对对话或已保存草稿，再决定下一步。'
                : 'The connection ended. Check conversation history or saved drafts before proceeding.';
  return (
    <div className="assistant-run">
      <p role="status" aria-live="polite">
        {text}
      </p>
      {status === 'running' || waiting ? (
        <button type="button" disabled={waiting} onClick={onStop}>
          {zh ? '停止处理' : 'Stop processing'}
        </button>
      ) : null}
      {status === 'unknown' || status === 'failed' ? (
        <button type="button" onClick={onCheck}>
          {zh ? '查看处理状态' : 'Check processing status'}
        </button>
      ) : null}
    </div>
  );
}
