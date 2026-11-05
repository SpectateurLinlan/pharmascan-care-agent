import { useEffect, useId, useRef, useState, type ReactNode } from 'react';
import type {
  JsonValue,
  WorkflowView,
  WorkflowEventHandler,
} from '../../../api/assistantWorkflows';
import { useLanguage } from '../../../i18n/language';
import { MedicationDate, MedicationTimes } from '../../enrollment/MedicationInputs';

type Form = {
  name: string;
  strength: string;
  amount: string;
  unit: string;
  kind: string;
  times: string;
  count: string;
  days: number[];
  hours: string;
  firstTime: string;
  start: string;
  end: string;
  guidance: string;
};

function object(value: JsonValue | undefined): Record<string, JsonValue> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
}

function text(value: JsonValue | undefined) {
  return typeof value === 'string' ? value : typeof value === 'number' ? String(value) : '';
}

function fromView(view: WorkflowView): Form {
  const fields = view.visible_fields;
  const rule = object(fields.frequency_rule);
  const basis = object(fields.dose_basis);
  const times = Array.isArray(rule.local_times)
    ? rule.local_times.filter((row): row is string => typeof row === 'string')
    : [];
  return {
    name: text(fields.medication_name),
    strength: text(basis.strength_text),
    amount: text(fields.dose_amount),
    unit: text(fields.dose_unit),
    kind: fields.is_prn === true ? 'prn' : text(rule.kind),
    times: times.join(', '),
    count: text(fields.times_per_day),
    days: Array.isArray(rule.days_of_week)
      ? rule.days_of_week.filter((row): row is number => typeof row === 'number')
      : [],
    hours: text(rule.every_hours),
    firstTime: object(rule.interval_anchor).time_source === 'default_0800' ? '' : (times[0] ?? ''),
    start: text(fields.course_start_date),
    end: text(fields.course_end_date),
    guidance: text(fields.food_instruction),
  };
}

/** Page inputs only. Applying them collects facts; it cannot review or activate a plan. */
export function AssistantEnrollmentFields({
  view,
  fieldNames,
  busy,
  onEvent,
  onDirtyChange,
  fixedIdentity = false,
}: {
  view: WorkflowView;
  fieldNames: string[];
  busy: boolean;
  onEvent: WorkflowEventHandler;
  onDirtyChange?: (dirty: boolean) => void;
  fixedIdentity?: boolean;
}) {
  const { language } = useLanguage();
  const id = useId();
  const say = (en: string, zh: string) => (language === 'zh' ? zh : en);
  const [form, setForm] = useState(() => fromView(view));
  const [dirty, setDirty] = useState(false);
  const [working, setWorking] = useState(false);
  const [notice, setNotice] = useState(false);
  const dirtyRef = useRef(false);
  const live = useRef(true);
  const sending = useRef(false);
  const callback = useRef(onDirtyChange);
  callback.current = onDirtyChange;
  const serverFields = JSON.stringify(view.visible_fields);
  useEffect(() => {
    if (!dirtyRef.current) setForm(fromView(view));
  }, [serverFields, view.revision]);
  useEffect(() => {
    onDirtyChange?.(dirty);
  }, [dirty, onDirtyChange]);
  useEffect(() => {
    live.current = true;
    return () => {
      live.current = false;
      callback.current?.(false);
    };
  }, []);

  function change<K extends keyof Form>(key: K, value: Form[K]) {
    dirtyRef.current = true;
    setDirty(true);
    setNotice(false);
    setForm((old) => ({ ...old, [key]: value }));
  }

  async function submit() {
    if (sending.current || busy) return;
    sending.current = true;
    setWorking(true);
    setNotice(false);
    const times = form.times
      .split(',')
      .map((row) => row.trim())
      .filter(Boolean);
    const frequency: JsonValue =
      form.kind === 'prn' || !form.kind
        ? null
        : form.kind === 'interval'
          ? {
              kind: 'interval',
              every_hours: form.hours ? Number(form.hours) : null,
              local_times: form.firstTime ? [form.firstTime] : [],
            }
          : {
              kind: form.kind,
              local_times: times,
              ...(form.kind === 'weekly' ? { days_of_week: form.days } : {}),
            };
    const values: Record<string, JsonValue> = {
      medication_name: form.name.trim() || null,
      dose_amount: form.amount ? Number(form.amount) : null,
      dose_unit: form.unit.trim() || null,
      dose_basis: {
        ...object(view.visible_fields.dose_basis),
        strength_text: form.strength,
        patient_checked: false,
      },
      frequency_rule: frequency,
      is_prn: form.kind === 'prn',
      times_per_day: form.kind === 'daily' && form.count ? Number(form.count) : null,
      course_start_date: form.start || null,
      course_end_date: form.end || null,
      food_instruction: form.guidance.trim() || null,
    };
    if (fixedIdentity) {
      delete values.medication_name;
      delete values.dose_basis;
    }
    try {
      const result = await onEvent({
        event_id: crypto.randomUUID(),
        expected_revision: view.revision,
        kind: 'provide_fields',
        values,
      });
      if (!live.current) return;
      if (result && result.task_id === view.task_id && result.revision > view.revision) {
        dirtyRef.current = false;
        setDirty(false);
        setForm(fromView(result));
      } else setNotice(true);
    } catch {
      if (live.current) setNotice(true);
    } finally {
      sending.current = false;
      if (live.current) setWorking(false);
    }
  }

  const wanted = new Set(fieldNames);
  const locked = busy || working;
  const groups: Array<{ key: string; needed: boolean; content: ReactNode }> = [
    {
      key: 'name',
      needed: fixedIdentity || wanted.has('medication_name'),
      content: (
        <label htmlFor={`${id}-name`}>
          {say('Medication name', '药物名称')}
          <input
            id={`${id}-name`}
            maxLength={160}
            readOnly={fixedIdentity}
            value={form.name}
            onChange={(event) => change('name', event.target.value)}
          />
        </label>
      ),
    },
    {
      key: 'strength',
      needed: wanted.has('dose_basis'),
      content: (
        <label htmlFor={`${id}-strength`}>
          {say('Product strength', '产品规格')}
          <input
            id={`${id}-strength`}
            maxLength={100}
            value={form.strength}
            onChange={(event) => change('strength', event.target.value)}
          />
        </label>
      ),
    },
    {
      key: 'amount',
      needed: wanted.has('dose_amount'),
      content: (
        <label htmlFor={`${id}-amount`}>
          {say('Amount per dose', '每次用量')}
          <input
            id={`${id}-amount`}
            type="number"
            step="any"
            value={form.amount}
            onChange={(event) => change('amount', event.target.value)}
          />
        </label>
      ),
    },
    {
      key: 'unit',
      needed: wanted.has('dose_unit'),
      content: (
        <label htmlFor={`${id}-unit`}>
          {say('Dose unit', '用量单位')}
          <input
            id={`${id}-unit`}
            maxLength={40}
            value={form.unit}
            onChange={(event) => change('unit', event.target.value)}
          />
        </label>
      ),
    },
    {
      key: 'schedule',
      needed:
        fieldNames.some((name) => name.startsWith('frequency')) || wanted.has('food_instruction'),
      content: (
        <>
          <label htmlFor={`${id}-schedule`}>
            {say('Schedule', '服用安排')}
            <select
              id={`${id}-schedule`}
              value={form.kind}
              onChange={(event) => change('kind', event.target.value)}
            >
              <option value="">{say('Choose from your instructions', '请按原始说明选择')}</option>
              <option value="daily">{say('Daily', '每日')}</option>
              <option value="weekly">{say('Weekly', '每周')}</option>
              <option value="interval">{say('Every N hours', '每隔若干小时')}</option>
              <option value="prn">{say('Only when needed', '按需服用')}</option>
            </select>
          </label>
          {form.kind === 'daily' ? (
            <label htmlFor={`${id}-count`}>
              {say('Recorded times per day', '说明中写明的每日次数')}
              <input
                id={`${id}-count`}
                type="number"
                min={1}
                max={24}
                value={form.count}
                onChange={(event) => change('count', event.target.value)}
              />
            </label>
          ) : null}
          {form.kind === 'daily' || form.kind === 'weekly' ? (
            <MedicationTimes value={form.times} onChange={(value) => change('times', value)} />
          ) : null}
          {form.kind === 'weekly' ? (
            <fieldset>
              <legend>{say('Weekdays', '星期')}</legend>
              {['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'].map(
                (day, index) => (
                  <label key={day}>
                    <input
                      type="checkbox"
                      checked={form.days.includes(index + 1)}
                      onChange={(event) =>
                        change(
                          'days',
                          event.target.checked
                            ? [...form.days, index + 1]
                            : form.days.filter((value) => value !== index + 1),
                        )
                      }
                    />
                    {say(day, `星期${['一', '二', '三', '四', '五', '六', '日'][index]}`)}
                  </label>
                ),
              )}
            </fieldset>
          ) : null}
          {form.kind === 'interval' ? (
            <>
              <label htmlFor={`${id}-hours`}>
                {say('Hours between doses', '每隔几小时')}
                <input
                  id={`${id}-hours`}
                  type="number"
                  min={1}
                  max={720}
                  value={form.hours}
                  onChange={(event) => change('hours', event.target.value)}
                />
              </label>
              <MedicationDate
                type="time"
                label={say('First dose time', '首次服用时间')}
                value={form.firstTime}
                onChange={(value) => change('firstTime', value)}
              />
            </>
          ) : null}
          <label htmlFor={`${id}-guidance`}>
            {form.kind === 'prn'
              ? say('Recorded as-needed guidance', '按需服用的原始指示')
              : say('Other recorded instructions', '其他原始用药说明')}
            <input
              id={`${id}-guidance`}
              maxLength={1000}
              value={form.guidance}
              onChange={(event) => change('guidance', event.target.value)}
            />
          </label>
        </>
      ),
    },
    {
      key: 'start',
      needed: wanted.has('course_start_date'),
      content: (
        <MedicationDate
          label={say('Course or first-dose start date', '疗程或首次服用日期')}
          value={form.start}
          onChange={(value) => change('start', value)}
        />
      ),
    },
    {
      key: 'end',
      needed: wanted.has('course_end_date'),
      content: (
        <MedicationDate
          label={say('Course end date', '疗程结束日期')}
          value={form.end}
          {...(form.start ? { min: form.start } : {})}
          onChange={(value) => change('end', value)}
        />
      ),
    },
  ];
  return (
    <form
      aria-label={say('Medication details', '药物资料')}
      onSubmit={(event) => {
        event.preventDefault();
        void submit();
      }}
    >
      <fieldset disabled={locked}>
        <legend>
          {say(
            'Fill the remaining details from your original instructions',
            '请按原始说明补充剩余资料',
          )}
        </legend>
        {groups
          .filter((group) => group.needed && (!fixedIdentity || group.key !== 'strength'))
          .map((group) => (
            <div className="field" key={group.key}>
              {group.content}
            </div>
          ))}
        <details>
          <summary>{say('Edit other details', '修改其他资料')}</summary>
          {groups
            .filter((group) => !group.needed && (!fixedIdentity || group.key !== 'strength'))
            .map((group) => (
              <div className="field" key={group.key}>
                {group.content}
              </div>
            ))}
        </details>
        <div className="actions">
          <button type="submit" disabled={locked || !dirty}>
            {say('Use these details', '使用这些资料继续')}
          </button>
          <button
            type="button"
            disabled={locked || !dirty}
            onClick={() => {
              dirtyRef.current = false;
              setDirty(false);
              setForm(fromView(view));
              setNotice(false);
            }}
          >
            {say('Undo unsent changes', '撤回尚未提交的修改')}
          </button>
        </div>
      </fieldset>
      {notice ? (
        <p role="status">
          {say(
            'The details were not accepted. Your input is still here.',
            '资料尚未被接受，输入内容仍保留在这里。',
          )}
        </p>
      ) : null}
    </form>
  );
}
