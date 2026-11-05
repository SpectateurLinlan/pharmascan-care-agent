import { useEffect, useRef, useState } from 'react';
import {
  api,
  type EvidenceDraft,
  type EvidenceTask,
  type WorkflowPatientBinding,
} from '../../../api/client';
import {
  workflowApi,
  type OriginalView,
  type WorkflowView,
  type WorkflowEventHandler,
} from '../../../api/assistantWorkflows';
import { useLanguage } from '../../../i18n/language';
import { EvidencePlanFields, type SourcePlanValues } from '../../enrollment/EvidencePlanFields';
import { PrintedLabelEvidence } from '../../media/PrintedLabelEvidence';
import { SourceReviewHints } from '../../media/SourceReviewHints';
import { ErrorNotice } from '../../../components/primitives';

export interface SourcePatientPort {
  task: typeof api.evidenceTask;
  sources: typeof api.evidenceSources;
  originals: typeof workflowApi.originals;
  saveOriginal: typeof api.saveEvidenceOriginal;
  review: typeof api.reviewEvidence;
}
const patientPort: SourcePatientPort = {
  task: (id) => api.evidenceTask(id),
  sources: (id) => api.evidenceSources(id),
  originals: (id) => workflowApi.originals(id),
  saveOriginal: (...args) => api.saveEvidenceOriginal(...args),
  review: (...args) => api.reviewEvidence(...args),
};
const empty: SourcePlanValues = {
  amount: '',
  unit: 'tablet',
  times: '',
  food: '',
  start: '',
  end: '',
  prn: false,
  category: 'unknown',
  patientEdited: false,
  reviewed: false,
};

/** Patient-only source stage. Progress reporting never supplies a clinical result ID. */
export function AssistantSourceActions({
  view,
  busy,
  onEvent,
  onClinicalChanged,
  onDirtyChange,
  onUpload,
  port = patientPort,
}: {
  view: WorkflowView;
  busy: boolean;
  onEvent: WorkflowEventHandler;
  onClinicalChanged?: (() => void) | undefined;
  onDirtyChange?: (dirty: boolean) => void;
  onUpload?: (() => void) | undefined;
  port?: SourcePatientPort;
}) {
  const { language, t } = useLanguage();
  const say = (en: string, zh: string) => (language === 'zh' ? zh : en);
  const [task, setTask] = useState<EvidenceTask | null>(null);
  const [sources, setSources] = useState<Awaited<ReturnType<SourcePatientPort['sources']>>>([]);
  const [originals, setOriginals] = useState<OriginalView[]>([]);
  const [selected, setSelected] = useState('');
  const [value, setValue] = useState<SourcePlanValues>(empty);
  const [loading, setLoading] = useState(false);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [retry, setRetry] = useState(0);
  const [dirty, setDirty] = useState(false);
  const pending = useRef(false);
  const live = useRef(true);
  const latest = useRef(view);
  const loaded = useRef('');
  latest.current = view;
  const ref = view.result_ref;
  const saved = view.visible_fields.source_saved === true;
  const preparedMarker =
    !saved &&
    view.capability_id === 'medication.source.add' &&
    ref?.kind === 'media_review' &&
    ref.id === view.task_id &&
    ref.version === view.revision;
  const sourceId =
    preparedMarker && typeof view.visible_fields.source_task_id === 'string'
      ? view.visible_fields.source_task_id
      : ref?.kind === 'enrollment_task'
        ? ref.id
        : null;
  const sourceAction = view.actions.find(
    (action) =>
      action.kind === 'existing_review' &&
      action.component_key === 'existing_source_review' &&
      (action.owned_ref.kind === 'enrollment_task' ||
        (preparedMarker && action.owned_ref.kind === 'media_review')) &&
      action.owned_ref.id === ref?.id &&
      action.expected_version === ref?.version,
  );
  const active =
    view.save_mode === 'allowed' &&
    view.state === 'awaiting_confirmation' &&
    Boolean(sourceAction) &&
    Boolean(sourceId);
  useEffect(() => {
    live.current = true;
    return () => {
      live.current = false;
    };
  }, []);
  useEffect(() => {
    onDirtyChange?.(dirty);
    return () => onDirtyChange?.(false);
  }, [dirty, onDirtyChange]);
  useEffect(() => {
    if (!active || !ref) return;
    let current = true;
    setLoading(true);
    setError(null);
    if (saved) {
      void Promise.all([port.task(ref.id), port.sources(ref.id), port.originals(view.task_id)])
        .then(([actual, linked, rows]) => {
          if (!current) return;
          if (actual.id !== ref.id || actual.version !== ref.version)
            throw new Error(
              say(
                'This source changed. Check task status before continuing.',
                '来源已发生变化，请先核查办理状态。',
              ),
            );
          setTask(actual);
          setSources(linked);
          const usable = rows.filter(
            (row) => row.state === 'saved' && row.extraction_status === 'succeeded',
          );
          setOriginals(usable);
          setSelected(usable.length === 1 ? usable[0]!.id : '');
          const key = `${actual.id}:${actual.version}`;
          if (loaded.current !== key) {
            const draft = actual.suggested_regimen;
            setValue({
              amount: draft?.dose_amount?.toString() ?? '',
              unit: draft?.dose_unit ?? 'tablet',
              times: draft?.frequency_rule?.local_times.join(', ') ?? '',
              food: draft?.food_instruction ?? '',
              start: draft?.course_start_date ?? '',
              end: draft?.course_end_date ?? '',
              prn: draft?.is_prn ?? false,
              category: actual.product.category,
              patientEdited: false,
              reviewed: false,
            });
            loaded.current = key;
            setDirty(false);
          } else setValue((previous) => ({ ...previous, reviewed: false }));
        })
        .catch((caught) => {
          if (current) setError(caught);
        })
        .finally(() => {
          if (current) setLoading(false);
        });
    } else {
      void port
        .originals(view.task_id)
        .then((rows) => {
          if (current) {
            const usable = rows.filter(
              (row) => row.state === 'saved' && row.extraction_status === 'succeeded',
            );
            setOriginals(usable);
            setSelected((previous) =>
              usable.some((row) => row.id === previous)
                ? previous
                : usable.length === 1
                  ? usable[0]!.id
                  : '',
            );
          }
        })
        .catch((caught) => {
          if (current) setError(caught);
        })
        .finally(() => {
          if (current) setLoading(false);
        });
    }
    return () => {
      current = false;
    };
    // Language changes translate controls without resetting unsent clinical inputs.
  }, [active, saved, ref?.id, ref?.version, view.task_id, view.revision, retry, port]);

  async function submit(save: (binding: WorkflowPatientBinding) => Promise<EvidenceTask>) {
    if (!active || pending.current || busy || !ref || !sourceId) return;
    const binding = { task_id: view.task_id, expected_revision: view.revision };
    pending.current = true;
    setWorking(true);
    setError(null);
    const current = () =>
      live.current &&
      latest.current.task_id === binding.task_id &&
      latest.current.revision === binding.expected_revision &&
      latest.current.save_mode === 'allowed' &&
      latest.current.state === 'awaiting_confirmation';
    try {
      const actual = await save(binding);
      if (!current()) return;
      if (actual.id !== sourceId)
        throw new Error(
          say(
            'The source result could not be confirmed. Check task status.',
            '尚未确认来源保存结果，请核查办理状态。',
          ),
        );
      setDirty(false);
      onClinicalChanged?.();
      await onEvent({
        event_id: crypto.randomUUID(),
        expected_revision: binding.expected_revision,
        kind: 'report_business_result',
        values: {},
      });
    } catch (caught) {
      if (current()) setError(caught);
    } finally {
      pending.current = false;
      if (live.current) setWorking(false);
    }
  }

  function review() {
    if (!task || !value.reviewed) return;
    const interval =
      task.suggested_regimen?.frequency_rule?.kind === 'interval'
        ? task.suggested_regimen.frequency_rule
        : null;
    const draft: EvidenceDraft = {
      patient_edited: value.patientEdited,
      medication_name: task.product.name,
      dose_amount: Number(value.amount),
      dose_unit: value.unit,
      is_prn: value.prn,
      frequency_rule: value.prn
        ? null
        : {
            kind: interval ? 'interval' : 'daily',
            local_times: value.times
              .split(',')
              .map((time) => time.trim())
              .filter(Boolean),
            days_of_week: [],
            every_hours: interval?.every_hours ?? null,
          },
      food_instruction: value.food || null,
      course_start_date: value.start || null,
      course_end_date: value.end || null,
    };
    void submit((binding) =>
      port.review(
        task.id,
        draft,
        false,
        { product_category: value.category, replace_active_plan: false },
        binding,
      ),
    );
  }

  if (!sourceAction || !ref || !sourceId || view.save_mode !== 'allowed') return null;
  return (
    <section
      className="assistant-source-review"
      aria-label={say('Review medication sources', '核对药物来源')}
    >
      {loading ? <p role="status">{say('Loading saved source…', '正在加载已保存来源…')}</p> : null}
      {error ? (
        <>
          <ErrorNotice error={error} />
          {!task ? (
            <button disabled={busy || working} onClick={() => setRetry((number) => number + 1)}>
              {say('Retry loading source', '重新加载来源')}
            </button>
          ) : null}
        </>
      ) : null}
      {!saved && !loading ? (
        <>
          <p>
            {say(
              'Your original photo is saved. Saving the source creates a medication registration for review; it does not activate a plan.',
              '原图已保存。保存来源后会建立待核对的药物登记，用药计划仍需单独确认。',
            )}
          </p>
          {originals.length > 1 ? (
            <label className="field">
              {say('Choose the original source photo', '选择来源原图')}
              <select
                disabled={busy || working}
                value={selected}
                onChange={(event) => setSelected(event.target.value)}
              >
                <option value="">{say('Choose a photo', '选择照片')}</option>
                {originals.map((row, index) => (
                  <option key={row.id} value={row.id}>
                    {say('Original photo', '来源原图')} {index + 1}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          {!originals.length ? (
            <p>
              {say(
                'No successfully read original is available. Check the saved originals below.',
                '尚无成功识别的原图，请核查下方已保存的原图。',
              )}
            </p>
          ) : null}
          <button
            className="primary"
            disabled={busy || working || !active || !selected}
            onClick={() => void submit((binding) => port.saveOriginal(sourceId, selected, binding))}
          >
            {say('Save this source and continue review', '保存此来源并继续核对')}
          </button>
        </>
      ) : null}
      {saved && task ? (
        <>
          <h3>{task.product.name}</h3>
          <p>
            {[task.product.strength, task.product.dose_form, task.product.formulation]
              .filter(Boolean)
              .join(' · ')}
          </p>
          {task.conflicts.length ? (
            <div role="alert">
              <h4>{t('Sources need clarification')}</h4>
              {task.conflicts.map((conflict, index) => (
                <p key={index}>{conflict.replace(/\s*\(source[^)]*\)/g, '')}</p>
              ))}
              <p>
                {t(
                  'The original evidence is retained. Add another source or ask a pharmacist to clarify the product.',
                )}
              </p>
            </div>
          ) : null}
          <details>
            <summary>
              {t('Linked source information')} · {sources.length}
            </summary>
            {sources.map((source) => (
              <article key={source.id}>
                <h4>
                  {t(
                    source.source_kind === 'package'
                      ? 'Packaging'
                      : source.source_kind === 'prescription'
                        ? 'Prescription image'
                        : 'Pharmacy label',
                  )}
                </h4>
                {source.extraction_evidence?.candidates.map((candidate, index) => (
                  <div key={index}>
                    {candidate.product.source_lines.map((line, lineIndex) => (
                      <p key={lineIndex}>{line}</p>
                    ))}
                    <PrintedLabelEvidence candidate={candidate} />
                  </div>
                ))}
              </article>
            ))}
          </details>
          <SourceReviewHints
            candidates={sources.flatMap((source) => source.extraction_evidence?.candidates ?? [])}
          />
          <p>
            {say(
              'Check the original instructions. This step saves an inactive draft; activation requires a separate confirmation.',
              '请对照原始说明核对。本步只保存未启用的草稿，启用仍需单独确认。',
            )}
          </p>
          <EvidencePlanFields
            task={task}
            value={value}
            onChange={(patch) => {
              setDirty(true);
              setValue((previous) => ({ ...previous, ...patch }));
            }}
            busy={busy || working || loading || !active}
            onPrepare={review}
            submitLabel={say('Save reviewed source and continue', '保存已核对来源并继续')}
          />
          {dirty ? (
            <button
              disabled={busy || working}
              onClick={() => {
                const draft = task.suggested_regimen;
                setValue({
                  amount: draft?.dose_amount?.toString() ?? '',
                  unit: draft?.dose_unit ?? 'tablet',
                  times: draft?.frequency_rule?.local_times.join(', ') ?? '',
                  food: draft?.food_instruction ?? '',
                  start: draft?.course_start_date ?? '',
                  end: draft?.course_end_date ?? '',
                  prn: draft?.is_prn ?? false,
                  category: task.product.category,
                  patientEdited: false,
                  reviewed: false,
                });
                setDirty(false);
              }}
            >
              {say('Undo unsent source details', '撤回尚未提交的来源资料')}
            </button>
          ) : null}
          {view.capability_id === 'medication.source.add' ? (
            <div>
              <h4>{t('Add another source')}</h4>
              <p>
                {say(
                  'Choose or upload the original, then save it separately. Apply or undo unsent details first.',
                  '请选择或上传原图，再单独保存。请先提交或撤回尚未发送的资料。',
                )}
              </p>
              {onUpload ? (
                <button disabled={busy || working || dirty} onClick={onUpload}>
                  {t('Add another source')}
                </button>
              ) : null}
              {originals.length > 1 ? (
                <label className="field">
                  {say('Choose the original source photo', '选择来源原图')}
                  <select
                    disabled={busy || working || dirty}
                    value={selected}
                    onChange={(event) => setSelected(event.target.value)}
                  >
                    <option value="">{say('Choose a photo', '选择照片')}</option>
                    {originals.map((row, index) => (
                      <option key={row.id} value={row.id}>
                        {say('Original photo', '来源原图')} {index + 1}
                      </option>
                    ))}
                  </select>
                </label>
              ) : null}
              <button
                disabled={busy || working || dirty || !selected}
                onClick={() =>
                  void submit((binding) => port.saveOriginal(sourceId, selected, binding))
                }
              >
                {say('Save selected additional source', '保存所选补充来源')}
              </button>
            </div>
          ) : null}
        </>
      ) : null}
    </section>
  );
}
