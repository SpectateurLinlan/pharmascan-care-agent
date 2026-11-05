import { useEffect, useRef, useState } from 'react';
import {
  workflowApi,
  type SourcePreviewResult,
  type WorkflowEventHandler,
  type WorkflowView,
} from '../../../api/assistantWorkflows';
import { useLanguage } from '../../../i18n/language';
import { workflowChoice } from '../model/assistantWorkflowActions';
import { PhotoAcquisition } from '../../media/PhotoAcquisition';
import { PrintedLabelEvidence } from '../../media/PrintedLabelEvidence';
import type { WorkflowSourceKind } from '../../../api/assistantWorkflows';
import './AssistantMediaActions.css';

const words: Record<string, [string, string]> = {
  'assistant.preview.label': ['Pharmacy label', '药房标签'],
  'assistant.preview.package': ['Medicine package', '药物包装'],
  'assistant.preview.prescription': ['Prescription', '处方'],
  unavailable: [
    'Source reading is unavailable. Your original is retained; no extraction was confirmed.',
    '来源读取服务不可用，原图仍保留，尚未确认提取结果。',
  ],
  rejected: [
    'The returned source could not be accepted. Your original is retained; check it manually or explicitly retry.',
    '无法接受本次来源提取结果，原图仍保留，请人工核对或明确选择重试。',
  ],
};

export function AssistantSourcePreview({
  view,
  busy,
  onEvent,
  onView,
  onDirtyChange,
  onOriginalUploadState,
}: {
  view: WorkflowView;
  busy: boolean;
  onEvent: WorkflowEventHandler;
  onView?: ((view: WorkflowView) => void) | undefined;
  onDirtyChange?: ((dirty: boolean) => void) | undefined;
  onOriginalUploadState?: ((task: string, active: boolean) => void) | undefined;
}) {
  const { language } = useLanguage();
  const say = (en: string, zh: string) => (language === 'zh' ? zh : en);
  const word = (key: string) => words[key]?.[language === 'zh' ? 1 : 0] ?? key;
  const [file, setFile] = useState<File | null>(null);
  const [fileOriginal, setFileOriginal] = useState<string | null>(null);
  const [working, setWorking] = useState(false);
  const [consent, setConsent] = useState(false);
  const [answer, setAnswer] = useState<SourcePreviewResult | null>(null);
  const [error, setError] = useState<'original' | 'query' | 'draft' | null>(null);
  const live = useRef(true);
  const pending = useRef(false);
  const uploadId = useRef<string | null>(null);
  const current = useRef(view);
  current.current = view;
  const callback = useRef(onDirtyChange);
  callback.current = onDirtyChange;
  const stateCallback = useRef(onOriginalUploadState);
  stateCallback.current = onOriginalUploadState;
  const source =
    typeof view.input_fields?.source_attachment_id === 'string'
      ? view.input_fields.source_attachment_id
      : null;
  const sourceKind = (view.input_fields?.source_kind ?? 'pharmacy_label') as WorkflowSourceKind;
  const filePending = Boolean(
    file && (view.save_mode === 'ephemeral' || fileOriginal === null || fileOriginal !== source),
  );
  useEffect(() => {
    live.current = true;
    return () => {
      live.current = false;
      stateCallback.current?.(view.task_id, false);
    };
  }, [view.task_id]);
  useEffect(() => {
    setAnswer(null);
    setConsent(false);
    setError(null);
    if (view.save_mode === 'ephemeral') {
      uploadId.current = null;
      setFileOriginal(null);
    }
  }, [view.task_id, view.revision, view.save_mode]);
  useEffect(() => {
    callback.current?.(working || filePending);
    return () => callback.current?.(false);
  }, [working, filePending]);
  const locked = busy || working;

  async function apply(event: Parameters<WorkflowEventHandler>[0]) {
    setError(null);
    try {
      await onEvent(event);
    } catch {
      if (live.current) setError('draft');
    }
  }

  async function saveOriginal() {
    if (!file || !onView || view.save_mode !== 'allowed' || pending.current) return;
    uploadId.current ??= crypto.randomUUID();
    pending.current = true;
    setWorking(true);
    setError(null);
    stateCallback.current?.(view.task_id, true);
    try {
      const result = await workflowApi.uploadPreviewOriginal(
        view.task_id,
        uploadId.current,
        file,
        view.revision,
      );
      if (!live.current || result.workflow.revision < current.current.revision) return;
      setFileOriginal(result.attachment.id);
      onView(result.workflow);
      if (result.workflow.input_fields?.source_attachment_id !== result.attachment.id)
        await onEvent({
          event_id: crypto.randomUUID(),
          expected_revision: result.workflow.revision,
          kind: 'provide_fields',
          values: { source_attachment_id: result.attachment.id },
        });
    } catch {
      if (live.current) setError('original');
    } finally {
      pending.current = false;
      stateCallback.current?.(view.task_id, false);
      if (live.current) setWorking(false);
    }
  }

  async function query() {
    if (
      locked ||
      !consent ||
      pending.current ||
      (view.save_mode === 'allowed' && (!source || filePending)) ||
      (view.save_mode === 'ephemeral' && !file)
    )
      return;
    pending.current = true;
    setWorking(true);
    setError(null);
    setAnswer(null);
    const revision = view.revision;
    const mode = view.save_mode;
    const valid = () =>
      live.current && current.current.revision === revision && current.current.save_mode === mode;
    try {
      let selected = fileOriginal === source && !filePending ? file : null;
      if (mode === 'ephemeral') selected = file;
      if (!selected && source) {
        const blob = await workflowApi.originalBlob(view.task_id, source);
        if (!valid()) return;
        selected = new File([blob], 'saved-source-preview', { type: blob.type });
      }
      if (!selected) throw new Error('Choose the current photo');
      const result = await workflowApi.previewSource(
        view.task_id,
        selected,
        revision,
        true,
        mode === 'ephemeral' ? sourceKind : undefined,
      );
      if (valid()) setAnswer(result);
    } catch {
      if (valid()) setError('query');
    } finally {
      pending.current = false;
      if (live.current) setWorking(false);
    }
  }

  if (['cancelled', 'suspended', 'completed'].includes(view.state)) return null;
  return (
    <div className="assistant-media" role="region" aria-label={say('Source preview', '来源预览')}>
      <div className="actions">
        {view.actions.flatMap((action) =>
          action.kind === 'choice'
            ? action.options.map((option) => (
                <button
                  key={`${action.action_id}:${option.value}`}
                  disabled={locked}
                  aria-pressed={sourceKind === option.value}
                  onClick={() => void apply(workflowChoice(view, action, option.value))}
                >
                  {option.label_text ?? word(option.label_key)}
                </button>
              ))
            : [],
        )}
      </div>
      <PhotoAcquisition
        file={file}
        disabled={locked}
        onFile={(selected) => {
          setFile(selected);
          setFileOriginal(null);
          uploadId.current = null;
          setConsent(false);
          setAnswer(null);
          setError(null);
        }}
      />
      {view.save_mode === 'ephemeral' ? (
        <>
          <p>
            {say(
              'The original stays on this page only. Preview results are temporary even when you save the draft.',
              '原图仅留在当前页面。即使保存草稿，预览结果也仅在当前页面显示。',
            )}
          </p>
          <button
            disabled={locked}
            onClick={() =>
              void apply({
                event_id: crypto.randomUUID(),
                expected_revision: view.revision,
                kind: 'allow_save',
                values: {},
              })
            }
          >
            {say('Save source preview draft', '保存来源预览草稿')}
          </button>
        </>
      ) : (
        <>
          {filePending ? (
            <button disabled={locked || !onView} onClick={() => void saveOriginal()}>
              {say('Save preview original', '保存预览原图')}
            </button>
          ) : null}
          {source && !filePending ? (
            <p>
              {say(
                'The preview original is saved. Saving did not start extraction.',
                '预览原图已保存，保存操作未启动提取。',
              )}
            </p>
          ) : null}
        </>
      )}
      <p>
        {say(
          'Previewed text is unreviewed evidence. It does not save a medication, confirm instructions or change a plan.',
          '预览文字尚未经核对，不会保存药物、确认用药说明或修改计划。',
        )}
      </p>
      <label className="consent">
        <input
          type="checkbox"
          checked={consent}
          disabled={locked}
          onChange={(event) => setConsent(event.target.checked)}
        />
        {say(
          'I allow this photo to be sent to read its label.',
          '我允许发送此照片以读取本次标签。',
        )}
      </label>
      <button
        className="primary"
        disabled={
          locked || !consent || (view.save_mode === 'allowed' ? !source || filePending : !file)
        }
        onClick={() => void query()}
      >
        {say('Preview source', '预览来源')}
      </button>
      {working ? (
        <p role="status">{say('Reading the current source…', '正在读取当前来源…')}</p>
      ) : null}
      {error ? (
        <p role="alert">
          {error === 'original'
            ? say(
                'The original save is unconfirmed. Your selected file is retained; check status before retrying.',
                '原图保存结果尚未确认，所选文件仍保留，请先核查状态再重试。',
              )
            : error === 'query'
              ? say(
                  'Source preview did not finish. Your original is retained. Retry only when you choose.',
                  '来源预览未完成，原图仍保留，您可以明确选择重试。',
                )
              : say(
                  'The task request did not finish. Your page photo is retained.',
                  '办理请求未完成，当前页面的照片仍保留。',
                )}
        </p>
      ) : null}
      {error === 'original' ? (
        <button
          disabled={locked}
          onClick={() =>
            void workflowApi
              .view(view.task_id)
              .then((next) => {
                if (live.current) onView?.(next);
              })
              .catch(() => {
                if (live.current) setError('original');
              })
          }
        >
          {say('Check original save status', '核查原图保存状态')}
        </button>
      ) : null}
      {answer ? (
        <div aria-live="polite">
          {answer.outcome !== 'success' ? (
            <p>{word(answer.outcome)}</p>
          ) : (
            <>
              <p>
                {say(
                  'Extraction is temporary and needs your review against the original. No instructions have been confirmed.',
                  '提取内容仅供临时预览，须与原文核对，尚未确认任何用药说明。',
                )}
              </p>
              {answer.preview?.candidates.length ? (
                answer.preview.candidates.map((candidate, index) => (
                  <article key={index}>
                    <h3>{candidate.product.name}</h3>
                    {candidate.product.strength ? <p>{candidate.product.strength}</p> : null}
                    <PrintedLabelEvidence candidate={candidate} previewOnly />
                    <details>
                      <summary>{say('Original source lines', '原始来源文字')}</summary>
                      <ul>
                        {candidate.product.source_lines.map((line, lineIndex) => (
                          <li key={lineIndex}>{line}</li>
                        ))}
                      </ul>
                    </details>
                  </article>
                ))
              ) : (
                <p>
                  {say(
                    'No medication information was read. Check the original label or enter verified details manually.',
                    '未读取到药物信息，请核对原始标签或手动输入可确认的资料。',
                  )}
                </p>
              )}
            </>
          )}
          <p>
            {say(
              'This preview creates no reviewed source, medication, schedule or dose record.',
              '本次预览不会建立已核对来源、药物、服药安排或服药记录。',
            )}
          </p>
          <p>
            {say(
              'Preview results stay on this page. Reopening the task requires another explicit read.',
              '预览结果仅留在当前页面，重新打开任务后需明确发起新的读取。',
            )}
          </p>
        </div>
      ) : null}
    </div>
  );
}
