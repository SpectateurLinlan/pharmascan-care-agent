import { useEffect, useRef, useState } from 'react';
import { api, type DemoStartResponse, type ConversationSummary } from '../../../api/client';
import type {
  JsonValue,
  WorkflowEventHandler,
  WorkflowRoute,
  WorkflowView,
} from '../../../api/assistantWorkflows';
import { isCareRoute } from '../../../shared/contracts/routes';
import { useLanguage } from '../../../i18n/language';
import { BottomSheet } from '../../../components/BottomSheet';
import { VoiceInput } from '../../../components/VoiceInput';

export interface SupportClientActions {
  adoptNew?: (session: DemoStartResponse) => void | Promise<void>;
  adoptResume?: (
    id: string,
    session: { conversation: ConversationSummary; session_id: string },
  ) => void | Promise<void>;
  cleared?: (() => void) | undefined;
  navigate?: ((route: WorkflowRoute, query: Record<string, string>) => void) | undefined;
  guide?: (() => void) | undefined;
  transcript?: (text: string) => void;
  play?: (text: string) => Promise<void>;
  stop?: () => void;
  voiceEnabled?: boolean;
  active?: boolean;
}
const record = (value: JsonValue | undefined): Record<string, JsonValue> =>
  value && typeof value === 'object' && !Array.isArray(value) ? value : {};
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
export function safeSupportNavigation(
  route: string,
  value: JsonValue | undefined,
): Record<string, string> | null {
  if (!isCareRoute(route) || value === null || Array.isArray(value) || typeof value !== 'object')
    return null;
  const entries = Object.entries(value ?? {});
  if (entries.length > 1) return null;
  if (entries.length === 0) return {};
  const [key, id] = entries[0]!;
  if (typeof id !== 'string' || !uuid.test(id)) return null;
  if (key === 'task' && route === 'care-tasks') return { task: id };
  if (
    key === 'id' &&
    [
      'medicine-detail',
      'medicine-history',
      'edit-medication',
      'check',
      'gallery',
      'medication-inventory',
    ].includes(route)
  )
    return { id };
  return null;
}

export function AssistantSupportActions({
  view,
  busy,
  onEvent,
  onDirtyChange,
  clientActions: client = {},
}: {
  view: WorkflowView;
  busy: boolean;
  onEvent: WorkflowEventHandler;
  onDirtyChange?: ((dirty: boolean) => void) | undefined;
  clientActions?: SupportClientActions | undefined;
}) {
  const { language, t } = useLanguage();
  const say = (en: string, zh: string) => (language === 'zh' ? zh : en);
  const [open, setOpen] = useState(false);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState(false);
  const [done, setDone] = useState(false);
  const [text, setText] = useState('');
  const pending = useRef(false);
  const live = useRef(true);
  const stop = useRef(client.stop);
  stop.current = client.stop;
  useEffect(() => {
    live.current = true;
    return () => {
      live.current = false;
      stop.current?.();
    };
  }, []);
  useEffect(() => {
    onDirtyChange?.(open || working);
    return () => onDirtyChange?.(false);
  }, [open, working, onDirtyChange]);
  const blocked = busy || working || client.active === false;
  const cap = view.capability_id;
  const bind = { task_id: view.task_id, expected_revision: view.revision };
  const action = view.actions.find((row) => row.kind === 'conversation');

  async function transition() {
    if (blocked || pending.current || !action || view.save_mode !== 'allowed') return;
    pending.current = true;
    setWorking(true);
    setError(false);
    try {
      if (action.action === 'new') {
        const result = await api.newConversation(bind);
        if (live.current) await client.adoptNew?.(result);
      } else if (action.action === 'resume' && action.conversation_id) {
        const result = await api.resumeConversation(action.conversation_id, bind);
        if (live.current) await client.adoptResume?.(action.conversation_id, result);
      } else if (action.action === 'clear') {
        await api.clearConversationHistory(bind);
        if (live.current) client.cleared?.();
      } else throw new Error('Select a conversation.');
      if (live.current) {
        setOpen(false);
        setDone(true);
      }
    } catch {
      if (live.current) setError(true);
    } finally {
      pending.current = false;
      if (live.current) setWorking(false);
    }
  }

  async function choose(id: string) {
    if (blocked) return;
    setWorking(true);
    setError(false);
    try {
      await onEvent({
        event_id: crypto.randomUUID(),
        expected_revision: view.revision,
        kind: 'provide_fields',
        values: { conversation_id: id },
      });
    } catch {
      if (live.current) setError(true);
    } finally {
      if (live.current) setWorking(false);
    }
  }

  if (view.state === 'suspended' || view.state === 'cancelled') return null;
  if (cap === 'assistant.usage')
    return (
      <div>
        {view.visible_fields.usage_available === true ? (
          <dl>
            <dt>{say('Conversations remaining today', '今日剩余对话次数')}</dt>
            <dd>{String(view.visible_fields.remaining)}</dd>
            <dt>{say('Resets at', '重置时间')}</dt>
            <dd>{String(view.visible_fields.next_reset_at)}</dd>
          </dl>
        ) : (
          <p role="status">
            {say(
              'Current usage is unavailable. This does not mean your quota is zero.',
              '暂时无法读取当前用量，这不表示您的额度为零。',
            )}
          </p>
        )}
      </div>
    );
  if (cap.startsWith('conversation.')) {
    const rows = Array.isArray(view.visible_fields.conversations)
      ? view.visible_fields.conversations.map(record)
      : [];
    const entries = Array.isArray(view.visible_fields.entries)
      ? view.visible_fields.entries.map(record)
      : [];
    const selected = record(view.visible_fields.conversation);
    const available =
      action?.action === 'new'
        ? Boolean(client.adoptNew)
        : action?.action === 'resume'
          ? Boolean(client.adoptResume)
          : Boolean(client.cleared);
    return (
      <div>
        {selected.title ? <h3>{String(selected.title)}</h3> : null}
        {rows.length ? (
          <ul>
            {rows.map((row, index) => (
              <li key={index}>
                {String(row.title)}
                {cap !== 'conversation.list' ? (
                  <button disabled={blocked} onClick={() => void choose(String(row.id))}>
                    {say('Select conversation', '选择会话')}
                  </button>
                ) : null}
              </li>
            ))}
          </ul>
        ) : cap === 'conversation.list' ? (
          <p>{say('No saved conversations.', '暂无已保存会话。')}</p>
        ) : null}
        {entries.map((row, index) => (
          <div key={index}>
            <p>{String(row.user_text)}</p>
            <p>{String(row.assistant_text)}</p>
          </div>
        ))}
        {typeof view.visible_fields.next_before === 'string' ? (
          <button
            disabled={blocked}
            onClick={() =>
              void onEvent({
                event_id: crypto.randomUUID(),
                expected_revision: view.revision,
                kind: 'provide_fields',
                values: { ...view.input_fields, before: view.visible_fields.next_before! },
              })
            }
          >
            {say('Earlier conversations or messages', '更早的会话或消息')}
          </button>
        ) : null}
        {action && !done ? (
          <button
            disabled={blocked || !available || view.save_mode !== 'allowed'}
            onClick={() => setOpen(true)}
          >
            {action.action === 'new'
              ? say('Start a new conversation', '开始新会话')
              : action.action === 'clear'
                ? say('Clear chat history', '清除聊天记录')
                : say('Resume conversation', '恢复会话')}
          </button>
        ) : null}
        {done ? (
          <p role="status">
            {say('The native conversation action completed.', '原生会话操作已完成。')}
          </p>
        ) : null}
        {open ? (
          <BottomSheet
            title={say('Review conversation action', '核对会话操作')}
            busy={working}
            onCancel={() => setOpen(false)}
          >
            <p>
              {action?.action === 'clear'
                ? say(
                    'Clear saved chats? Saved workflow drafts and medication records are retained.',
                    '清除已保存聊天？已保存的办理草稿和药物记录会保留。',
                  )
                : say(
                    'Switch to a fresh session. Old confirmations will not be restored.',
                    '切换到新会话，不会恢复旧确认权限。',
                  )}
            </p>
            <button disabled={blocked} onClick={() => void transition()}>
              {say('Confirm conversation action', '确认会话操作')}
            </button>
            <button disabled={working} onClick={() => setOpen(false)}>
              {t('Cancel')}
            </button>
            {error ? (
              <p role="alert">
                {say(
                  'The result could not be confirmed. Your drafts remain. Retry checks the earlier native result.',
                  '暂时无法确认结果，草稿仍保留。重试会核查此前的原生结果。',
                )}
              </p>
            ) : null}
          </BottomSheet>
        ) : null}
        {error && !open ? (
          <p role="alert">{say('Could not load this conversation.', '暂时无法读取会话。')}</p>
        ) : null}
      </div>
    );
  }
  if (cap === 'speech.input')
    return (
      <div>
        {client.voiceEnabled && client.transcript ? (
          <>
            <VoiceInput disabled={blocked} onTranscript={client.transcript} />
            <p>
              {say(
                'Recognized text goes to the message box. Review it and press Send yourself.',
                '识别文字会进入消息框，请核对后手动发送。',
              )}
            </p>
          </>
        ) : (
          <p role="status">
            {say(
              'Voice input is unavailable here. Check voice settings or type your message.',
              '当前无法使用语音输入，请检查语音设置或输入文字。',
            )}
          </p>
        )}
      </div>
    );
  if (cap === 'speech.playback')
    return (
      <div>
        <label className="field">
          {say('Text to read', '要朗读的文字')}
          <textarea
            maxLength={2000}
            value={text}
            onChange={(event) => setText(event.target.value)}
            disabled={blocked}
          />
        </label>
        <button
          disabled={blocked || !client.play || !client.voiceEnabled || !text.trim()}
          onClick={() => {
            setError(false);
            void client.play?.(text).catch(() => setError(true));
          }}
        >
          {say('Read text aloud', '朗读文字')}
        </button>
        <button disabled={!client.stop} onClick={() => client.stop?.()}>
          {t('Stop audio')}
        </button>
        <p>
          {say(
            'Playback uses your existing voice and provider settings.',
            '朗读使用您现有的语音及服务设置。',
          )}
        </p>
        {error ? (
          <p role="alert">
            {say(
              'Audio playback is unavailable. Your text remains.',
              '暂时无法播放语音，文字仍保留。',
            )}
          </p>
        ) : null}
      </div>
    );
  const navigation = view.actions.find((row) => row.kind === 'navigate');
  const query = navigation
    ? safeSupportNavigation(navigation.route, view.visible_fields.navigation_query ?? {})
    : null;
  return (
    <div>
      {cap === 'navigation.open' && !navigation ? (
        <label className="field">
          {say('Page to open', '要打开的页面')}
          <select
            defaultValue=""
            disabled={blocked}
            onChange={(event) =>
              void onEvent({
                event_id: crypto.randomUUID(),
                expected_revision: view.revision,
                kind: 'provide_fields',
                values: { destination: { kind: 'navigate', route: event.target.value } },
              })
            }
          >
            <option value="">{say('Choose a page', '选择页面')}</option>
            {(
              [
                'today',
                'medicines',
                'records',
                'me',
                'care-tasks',
                'health-notes',
                'gallery',
                'settings',
                'help',
              ] as const
            ).map((route) => (
              <option key={route} value={route}>
                {t(
                  {
                    today: 'Today',
                    medicines: 'Medicines',
                    records: 'Records',
                    me: 'Me',
                    'care-tasks': 'Care tasks',
                    'health-notes': 'Health notes',
                    gallery: 'Gallery',
                    settings: 'Settings',
                    help: 'Help',
                  }[route],
                )}
              </option>
            ))}
          </select>
        </label>
      ) : null}
      {navigation ? (
        <button
          disabled={blocked || (cap === 'guide.start' ? !client.guide : !client.navigate)}
          onClick={() => {
            if (cap === 'guide.start') client.guide?.();
            else if (query) client.navigate?.(navigation.route, query);
            else setError(true);
          }}
        >
          {cap === 'guide.start'
            ? say('Start app guide', '开始应用导览')
            : cap === 'help.open'
              ? say('Open help', '打开帮助')
              : say('Open page', '打开页面')}
        </button>
      ) : null}
      {error ? (
        <p role="alert">
          {say(
            'This page target is unavailable. Choose it again.',
            '当前页面目标不可用，请重新选择。',
          )}
        </p>
      ) : null}
    </div>
  );
}
