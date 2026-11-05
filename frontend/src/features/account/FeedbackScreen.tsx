import { FeedbackFields } from './FeedbackFields';
import { useState } from 'react';
import { api } from '../../api/client';
import { useLanguage } from '../../i18n/language';
import { AutoDismissNotice, Card, ErrorNotice } from '../../components/primitives';
import { Screen } from '../../components/layout';

export function FeedbackScreen() {
  const { t } = useLanguage();
  const [category, setCategory] = useState<'issue' | 'suggestion'>('issue');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [id] = useState(() => crypto.randomUUID());

  async function submit() {
    if (busy || message.trim().length < 5) return;
    setBusy(true);
    setError(null);
    try {
      await api.feedback({ id, category, message: message.trim() });
      setSaved(true);
    } catch (error) {
      setError(error);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Screen title="Feedback & Suggestions" className="feedback-screen">
      <Card>
        <p>
          {t(
            'Tell us about an app issue or an improvement. Do not include passwords, verification codes or unnecessary sensitive medical information.',
          )}
        </p>
        {saved ? (
          <>
            <p role="status">
              {t(
                'Your feedback was saved to your account feedback record. This does not mean it was emailed or reviewed.',
              )}
            </p>
            <AutoDismissNotice>{t('Feedback saved.')}</AutoDismissNotice>
          </>
        ) : (
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void submit();
            }}
          >
            <FeedbackFields
              draft={{ category, message }}
              busy={busy}
              onChange={(next) => {
                setCategory(next.category);
                setMessage(next.message);
              }}
            />
            <button className="primary" type="submit" disabled={busy || message.trim().length < 5}>
              {busy ? t('Submitting...') : t('Send feedback')}
            </button>
          </form>
        )}
        {error ? <ErrorNotice error={error} /> : null}
      </Card>
    </Screen>
  );
}
