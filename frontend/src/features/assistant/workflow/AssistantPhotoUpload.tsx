import { useEffect, useRef, useState } from 'react';
import { api, type GalleryImage } from '../../../api/client';
import {
  workflowApi,
  type JsonValue,
  type WorkflowEventHandler,
  type WorkflowView,
} from '../../../api/assistantWorkflows';
import { useLanguage } from '../../../i18n/language';
import { workflowChoice } from '../model/assistantWorkflowActions';
import { PhotoAcquisition } from '../../media/PhotoAcquisition';
import { PhotoMetadataFields } from '../../media/MediaMetadataFields';
import { BottomSheet } from '../../../components/BottomSheet';
import './AssistantMediaActions.css';

export function AssistantPhotoUpload({
  view,
  busy,
  onEvent,
  onView,
  onDirtyChange,
  onClinicalChanged,
  onOriginalUploadState,
}: {
  view: WorkflowView;
  busy: boolean;
  onEvent: WorkflowEventHandler;
  onView?: ((view: WorkflowView) => void) | undefined;
  onDirtyChange?: ((dirty: boolean) => void) | undefined;
  onClinicalChanged?: (() => void) | undefined;
  onOriginalUploadState?: ((task: string, active: boolean) => void) | undefined;
}) {
  const { language, t } = useLanguage();
  const say = (en: string, zh: string) => (language === 'zh' ? zh : en);
  const [file, setFile] = useState<File | null>(null);
  const [fileOriginal, setFileOriginal] = useState<string | null>(null);
  const [kind, setKind] = useState(
    (view.input_fields?.image_kind ?? 'package') as GalleryImage['image_kind'],
  );
  const [description, setDescription] = useState(
    String(view.input_fields?.source_description ?? ''),
  );
  const [dirty, setDirty] = useState(false);
  const [working, setWorking] = useState(false);
  const [open, setOpen] = useState(false);
  const [consent, setConsent] = useState(false);
  const [error, setError] = useState<'original' | 'draft' | 'upload' | null>(null);
  const [uncertain, setUncertain] = useState(false);
  const uploadId = useRef<string | null>(null);
  const live = useRef(true);
  const pending = useRef(false);
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
    callback.current?.(dirty || working || open || filePending);
    return () => callback.current?.(false);
  }, [dirty, working, open, filePending]);
  useEffect(() => {
    setOpen(false);
    setConsent(false);
    setUncertain(false);
    setDirty(false);
    setError(null);
    if (view.save_mode === 'ephemeral') {
      uploadId.current = null;
      setFileOriginal(null);
    }
    setKind((view.input_fields?.image_kind ?? 'package') as GalleryImage['image_kind']);
    setDescription(String(view.input_fields?.source_description ?? ''));
    // A revision or save-mode transition preserves the page File. Only the task/owner key discards it.
  }, [
    view.revision,
    view.save_mode,
    view.input_fields?.image_kind,
    view.input_fields?.source_description,
  ]);
  const bound =
    view.save_mode === 'allowed' &&
    view.state === 'awaiting_confirmation' &&
    view.result_ref?.kind === 'media_review' &&
    view.actions.some(
      (action) =>
        action.kind === 'existing_review' &&
        action.component_key === 'existing_media_management' &&
        action.owned_ref.id === view.result_ref?.id,
    );
  const choice = view.actions.find(
    (action) => action.kind === 'choice' && action.action_id === 'photo.medication',
  );
  const locked = busy || working;

  async function event(
    kind: Parameters<WorkflowEventHandler>[0]['kind'],
    values: Record<string, JsonValue> = {},
    revision = view.revision,
  ) {
    const result = await onEvent({
      event_id: crypto.randomUUID(),
      expected_revision: revision,
      kind,
      values,
    });
    if (
      !result ||
      result.task_id !== view.task_id ||
      result.revision < revision ||
      (kind !== 'report_business_result' && result.revision === revision)
    )
      throw new Error('Check the current photo draft.');
    return result;
  }

  async function apply(
    kind: Parameters<WorkflowEventHandler>[0]['kind'],
    values: Record<string, JsonValue> = {},
  ) {
    setError(null);
    try {
      await event(kind, values);
      if (live.current) setDirty(false);
    } catch {
      if (live.current) setError('draft');
    }
  }

  async function checkOriginal() {
    setError(null);
    try {
      const next = await workflowApi.view(view.task_id);
      if (live.current) onView?.(next);
    } catch {
      if (live.current) setError('original');
    }
  }

  async function saveOriginal() {
    if (!file || !onView || view.save_mode !== 'allowed' || pending.current) return;
    const selected = file;
    uploadId.current ??= crypto.randomUUID();
    pending.current = true;
    setWorking(true);
    setError(null);
    stateCallback.current?.(view.task_id, true);
    try {
      const result = await workflowApi.uploadReferenceOriginal(
        view.task_id,
        uploadId.current,
        selected,
        view.revision,
      );
      if (!live.current || result.workflow.revision < current.current.revision) return;
      setFileOriginal(result.attachment.id);
      onView(result.workflow);
      if (result.workflow.input_fields?.source_attachment_id !== result.attachment.id) {
        await event(
          'provide_fields',
          { source_attachment_id: result.attachment.id },
          result.workflow.revision,
        );
      }
    } catch {
      if (live.current) setError('original');
    } finally {
      pending.current = false;
      stateCallback.current?.(view.task_id, false);
      if (live.current) setWorking(false);
    }
  }

  async function checkResult() {
    const next = await event('report_business_result');
    if (!live.current) return;
    setOpen(false);
    if (next.state === 'completed') {
      setFile(null);
      setUncertain(false);
      onClinicalChanged?.();
    } else if (
      next.state === 'awaiting_confirmation' &&
      next.visible_fields.upload_attempted === false &&
      next.result_ref?.id === view.result_ref?.id
    ) {
      setUncertain(false);
      setError(null);
    }
  }

  async function confirm() {
    if (
      !bound ||
      !consent ||
      pending.current ||
      uncertain ||
      !source ||
      typeof view.input_fields?.medication_id !== 'string'
    )
      return;
    pending.current = true;
    setWorking(true);
    setError(null);
    try {
      let original = fileOriginal === source ? file : null;
      if (!original) {
        const blob = await workflowApi.originalBlob(view.task_id, source);
        if (!live.current) return;
        original = new File([blob], 'saved-reference-photo', { type: blob.type });
      }
      await api.addReference(
        view.input_fields.medication_id,
        original,
        view.input_fields.image_kind as GalleryImage['image_kind'],
        String(view.input_fields.source_description),
        true,
        false,
        { task_id: view.task_id, expected_revision: view.revision },
      );
      await checkResult();
    } catch {
      if (live.current) {
        setError('upload');
        setUncertain(true);
      }
    } finally {
      pending.current = false;
      if (live.current) setWorking(false);
    }
  }

  const notice = error ? (
    <p role="alert">
      {error === 'original'
        ? say(
            'The original save is unconfirmed. Your selected file is still on this page. Check its status before retrying.',
            '原图保存结果尚未确认，所选文件仍保留在当前页面，请先核查状态再重试。',
          )
        : error === 'upload'
          ? say(
              'The gallery result is unconfirmed. Check the result before retrying; your draft is retained.',
              '图库保存结果尚未确认，请先核查结果再重试，草稿仍保留。',
            )
          : say(
              'The draft request did not finish. Your photo and entered details are still here.',
              '草稿请求未完成，照片和输入资料仍保留。',
            )}
    </p>
  ) : null;
  if (view.state === 'completed')
    return (
      <p>
        {view.visible_fields.historical_result
          ? say('The earlier upload receipt is retained.', '此前的上传回执仍保留。')
          : view.visible_fields.duplicate
            ? say(
                'This exact photo was already present. No second photo was added.',
                '相同照片已存在，没有重复添加。',
              )
            : say(
                'The gallery photo was saved and its record checked.',
                '图库照片已保存，并已核查记录。',
              )}
      </p>
    );
  if (view.state === 'suspended' || view.state === 'cancelled') return null;
  if (
    view.result_ref?.kind === 'media_review' &&
    (!bound || view.prompt_key === 'assistant.photo.check_result')
  )
    return (
      <div>
        <button
          disabled={locked}
          onClick={() => void checkResult().catch(() => setError('upload'))}
        >
          {say('Check photo result', '核查照片结果')}
        </button>
        {notice}
      </div>
    );
  if (bound)
    return (
      <div className="assistant-media">
        <button disabled={locked} onClick={() => setOpen(true)}>
          {say('Review gallery photo', '核对图库照片')}
        </button>
        {!view.visible_fields.upload_attempted ? (
          <button
            disabled={locked}
            onClick={() =>
              void apply('provide_fields', {
                image_kind: view.input_fields?.image_kind ?? null,
                source_description: view.input_fields?.source_description ?? null,
              })
            }
          >
            {say('Edit photo details', '编辑照片资料')}
          </button>
        ) : null}
        {open ? (
          <BottomSheet
            title={say('Add this photo to your medication gallery?', '将这张照片添加到药物图库？')}
            busy={working}
            onCancel={() => setOpen(false)}
          >
            <p>{String(view.visible_fields.medication_name ?? '')}</p>
            <p>{String(view.input_fields?.source_description ?? '')}</p>
            <p>
              {say(
                'This links a patient-supplied photo. It does not verify medication identity, dosage or safe use, and will not enable automatic comparison.',
                '此操作关联患者提供的照片，不确认药物身份、剂量或安全用法，也不会启用自动比对。',
              )}
            </p>
            <label className="consent">
              <input
                type="checkbox"
                checked={consent}
                disabled={working || uncertain}
                onChange={(event) => setConsent(event.target.checked)}
              />
              {say(
                'I checked that this photo belongs with this medication and allow private photo processing.',
                '我已核对照片与这项药物的关联，并允许私有照片处理。',
              )}
            </label>
            {notice}
            {uncertain ? (
              <button
                disabled={working}
                onClick={() => void checkResult().catch(() => setError('upload'))}
              >
                {say('Check photo result', '核查照片结果')}
              </button>
            ) : null}
            <div className="actions">
              <button
                className="primary"
                disabled={!consent || working || uncertain}
                onClick={() => void confirm()}
              >
                {say('Add photo to gallery', '添加到图库')}
              </button>
              <button disabled={working} onClick={() => setOpen(false)}>
                {t('Cancel')}
              </button>
            </div>
          </BottomSheet>
        ) : (
          notice
        )}
      </div>
    );
  const page = Number(view.visible_fields.page ?? 0);
  const pages = Number(view.visible_fields.page_count ?? 1);
  return (
    <div className="assistant-media">
      {choice?.kind === 'choice' ? (
        <div className="actions">
          {choice.options.map((option) => (
            <button
              key={option.value}
              disabled={locked}
              onClick={() => {
                const selected = workflowChoice(view, choice, option.value);
                void apply(selected.kind, selected.values);
              }}
            >
              {say('Select', '选择')}: {option.label_text}
            </button>
          ))}
        </div>
      ) : null}
      {view.input_fields?.medication_id ? (
        <>
          <h3>{String(view.visible_fields.medication_name ?? '')}</h3>
          <PhotoAcquisition
            file={file}
            disabled={locked}
            onFile={(selected) => {
              setFile(selected);
              setFileOriginal(null);
              uploadId.current = null;
              setError(null);
            }}
          />
          <PhotoMetadataFields
            kind={kind}
            description={description}
            t={t}
            disabled={locked}
            onKind={(value) => {
              setKind(value);
              setDirty(true);
            }}
            onDescription={(value) => {
              setDescription(value);
              setDirty(true);
            }}
          />
          <button
            disabled={locked || !description.trim()}
            onClick={() =>
              void apply('provide_fields', { image_kind: kind, source_description: description })
            }
          >
            {say('Apply photo details', '使用照片资料')}
          </button>
          {view.save_mode === 'ephemeral' ? (
            <>
              <p>
                {say(
                  'This photo stays on this page only. Save the draft to retain the original; adding to the gallery still needs separate confirmation.',
                  '照片仅保留在当前页面。保存草稿后才会保留原图，添加到图库仍需单独确认。',
                )}
              </p>
              <button disabled={locked || dirty} onClick={() => void apply('allow_save')}>
                {say('Save photo draft', '保存照片草稿')}
              </button>
            </>
          ) : (
            <>
              {filePending ? (
                <button disabled={locked || dirty || !onView} onClick={() => void saveOriginal()}>
                  {say('Save original photo', '保存原始照片')}
                </button>
              ) : null}
              {source && !filePending ? (
                <p>
                  {say(
                    'The original photo is saved. It has not been sent for medication recognition.',
                    '原始照片已保存，未发送进行药物识别。',
                  )}
                </p>
              ) : null}
              {view.state === 'ready_for_review' ? (
                <button
                  disabled={locked || dirty || filePending}
                  onClick={() => void apply('prepare_confirmation')}
                >
                  {say('Prepare photo review', '准备照片核对')}
                </button>
              ) : null}
            </>
          )}
        </>
      ) : null}
      {page > 0 ? (
        <button disabled={locked} onClick={() => void apply('provide_fields', { page: page - 1 })}>
          {say('Previous page', '上一页')}
        </button>
      ) : null}
      {page + 1 < pages ? (
        <button disabled={locked} onClick={() => void apply('provide_fields', { page: page + 1 })}>
          {say('Next page', '下一页')}
        </button>
      ) : null}
      {error === 'original' ? (
        <button disabled={locked} onClick={() => void checkOriginal()}>
          {say('Check original save status', '核查原图保存状态')}
        </button>
      ) : null}
      {notice}
    </div>
  );
}
