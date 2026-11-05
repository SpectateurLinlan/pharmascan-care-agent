import { useLanguage } from '../../i18n/language';

export interface FeedbackDraft {
  category: 'issue' | 'suggestion';
  message: string;
}
export function FeedbackFields({
  draft,
  onChange,
  busy = false,
}: {
  draft: FeedbackDraft;
  onChange: (value: FeedbackDraft) => void;
  busy?: boolean;
}) {
  const { t } = useLanguage();
  return (
    <>
      <label className="field">
        {t('Category')}
        <select
          disabled={busy}
          value={draft.category}
          onChange={(event) =>
            onChange({
              ...draft,
              category: event.target.value === 'suggestion' ? 'suggestion' : 'issue',
            })
          }
        >
          <option value="issue">{t('App issue')}</option>
          <option value="suggestion">{t('Suggestion')}</option>
        </select>
      </label>
      <label className="field">
        {t('Description')}
        <textarea
          disabled={busy}
          required
          minLength={5}
          maxLength={2000}
          value={draft.message}
          onChange={(event) => onChange({ ...draft, message: event.target.value })}
        />
      </label>
    </>
  );
}
