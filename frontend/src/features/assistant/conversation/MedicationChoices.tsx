import { useEffect, useState } from 'react';
import type {
  MedicationChoice,
  MedicationSelection,
  NameChoice,
  NameSelection,
} from '../../../api/client';
import { useLanguage } from '../../../i18n/language';

export function MedicationChoices({
  choice,
  disabled,
  onChoose,
}: {
  choice: MedicationChoice;
  disabled: boolean;
  onChoose: (selection: MedicationSelection, label: string) => void;
}) {
  const { t } = useLanguage();
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  const expired = Date.parse(choice.expires_at) <= now;
  return (
    <section className="medication-choices" aria-label={t('Choose a medicine')}>
      {choice.options.map((option) => (
        <button
          type="button"
          key={option.medication_id}
          disabled={disabled || expired}
          onClick={() =>
            onChoose({ choice_id: choice.id, medication_id: option.medication_id }, option.label)
          }
        >
          {option.label}
        </button>
      ))}
      {expired ? (
        <p role="status">{t('These choices expired. Ask your question again to refresh them.')}</p>
      ) : null}
    </section>
  );
}

export function MedicationNameChoices({
  choice,
  disabled,
  onChoose,
}: {
  choice: NameChoice;
  disabled: boolean;
  onChoose: (selection: NameSelection, label: string) => void;
}) {
  const { t, language } = useLanguage();
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  const expired =
    !Number.isFinite(Date.parse(choice.expires_at)) || Date.parse(choice.expires_at) <= now;
  return (
    <section
      className="medication-choices"
      aria-label={language === 'zh' ? '确认药名' : 'Confirm the medicine name'}
    >
      <p>
        {language === 'zh'
          ? '您指的是以下药名吗？确认后再查询，不会将其添加到您的药物清单。'
          : 'Did you mean this medicine name? Confirm to search; this will not add it to your medication list.'}
      </p>
      {choice.options.map((option) => (
        <button
          type="button"
          key={option.id}
          disabled={disabled || expired}
          onClick={() =>
            onChoose(
              { choice_id: choice.id, candidate_id: option.id, expected_version: choice.version },
              option.display_name,
            )
          }
        >
          {option.display_name}
        </button>
      ))}
      {expired ? (
        <p role="status">{t('These choices expired. Ask your question again to refresh them.')}</p>
      ) : null}
    </section>
  );
}
