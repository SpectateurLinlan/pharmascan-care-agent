/** Show a local composer while identity/session setup runs; never queue a send. */
import { useLayoutEffect, useRef, useState, type ComponentProps } from 'react';
import type { StartupDraft } from './startupDraft';
import { Icon } from '../components/Icon';
import { AssistantScreen } from '../features/assistant/conversation/AssistantScreen';
import { ConversationSurface } from '../features/conversations/ConversationSurface';
import { useLanguage } from '../i18n/language';

type Props = ComponentProps<typeof AssistantScreen> & {
  connectionReady: boolean;
  connectionError?: unknown;
  onRetryConnection: () => void;
  startupDraft?: StartupDraft | undefined;
};

export function AssistantEntry({
  connectionReady,
  connectionError,
  onRetryConnection,
  startupDraft,
  ...props
}: Props) {
  const { t } = useLanguage();
  const [draft, setDraft] = useState(startupDraft?.text ?? '');
  const [focused, setFocused] = useState(startupDraft?.focused ?? false);
  const [selection, setSelection] = useState(startupDraft?.selection ?? { start: 0, end: 0 });
  const pendingInput = useRef<HTMLInputElement>(null);
  useLayoutEffect(() => {
    if (startupDraft?.focused && pendingInput.current) {
      pendingInput.current.focus({ preventScroll: true });
      pendingInput.current.setSelectionRange(
        startupDraft.selection.start,
        startupDraft.selection.end,
      );
      // focus fires onFocus with the pre-restoration caret; retain the final range.
      setSelection(startupDraft.selection);
    }
  }, [startupDraft]);
  const [composing, setComposing] = useState(false);
  const captureSelection = (input: HTMLInputElement) =>
    setSelection({
      start: input.selectionStart ?? input.value.length,
      end: input.selectionEnd ?? input.value.length,
    });
  if (connectionReady && props.ownerId && props.sessionId && !composing) {
    return (
      <AssistantScreen
        {...props}
        initialText={draft}
        {...(focused ? { initialSelection: selection } : {})}
      />
    );
  }
  return (
    <ConversationSurface
      open={false}
      workspace={props.workspace ?? false}
      onClose={props.onClose}
      locked={false}
    >
      <section
        className={props.compact ? 'companion-composer today-assistant card' : 'assistant-view'}
        aria-label={t('Medication companion')}
      >
        <div className="today-assistant__heading">
          <Icon name="message" />
          <h2>MediThread Assistant</h2>
          {props.compact && props.onExpand ? (
            <button type="button" className="today-assistant__expand" onClick={props.onExpand}>
              {t('Open full chat')}
              <Icon name="chevron-right" />
            </button>
          ) : null}
        </div>
        <p role={connectionError ? 'alert' : 'status'}>
          {t(
            connectionError
              ? 'Assistant connection is unavailable. Your unsent message is kept on this page.'
              : 'Connecting to your assistant. You can type while we connect.',
          )}
        </p>
        {connectionError ? (
          <button type="button" onClick={onRetryConnection}>
            {t('Retry connecting')}
          </button>
        ) : null}
        <form
          className="composer-row composer-row--connecting"
          data-guide="assistant-composer"
          onSubmit={(event) => event.preventDefault()}
        >
          <input
            ref={pendingInput}
            aria-label={t('Review your message before sending')}
            placeholder={t('Ask about your medication...')}
            maxLength={2000}
            value={draft}
            onChange={(event) => {
              setDraft(event.target.value);
              captureSelection(event.currentTarget);
            }}
            onFocus={(event) => {
              setFocused(true);
              captureSelection(event.currentTarget);
            }}
            onBlur={() => setFocused(false)}
            onSelect={(event) => captureSelection(event.currentTarget)}
            onCompositionStart={() => setComposing(true)}
            onCompositionEnd={(event) => {
              setDraft(event.currentTarget.value);
              captureSelection(event.currentTarget);
              setComposing(false);
            }}
          />
          <button className="primary composer-send" type="submit" disabled aria-label={t('Send')}>
            <Icon name="send" />
          </button>
        </form>
      </section>
    </ConversationSurface>
  );
}
