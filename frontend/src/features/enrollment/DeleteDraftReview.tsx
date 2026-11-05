import { useLanguage } from '../../i18n/language';
import { BottomSheet } from '../../components/BottomSheet';
import { ErrorNotice } from '../../components/primitives';

/** Reuse the application's independent patient review and deletion consequences. */
export function DeleteDraftReview({
  name,
  busy,
  error,
  failureMessage,
  impact,
  onConfirm,
  onCancel,
  onCheckResult,
}: {
  name: string;
  busy: boolean;
  error: unknown;
  failureMessage?: string | undefined;
  impact?: { plans: number; sources: number; wholeMedication: boolean } | undefined;
  onConfirm: () => void;
  onCancel: () => void;
  onCheckResult?: (() => void) | undefined;
}) {
  const { t, language } = useLanguage();
  return (
    <BottomSheet title={t('Delete this draft?')} busy={busy} onCancel={onCancel}>
      <p>{name}</p>
      <p>
        {t(
          'This removes the unconfirmed registration and its exclusive draft data. Confirmed history and shared sources are kept. This cannot be undone.',
        )}
      </p>
      {impact ? (
        <p>
          {language === 'zh'
            ? `将移除 ${impact.plans} 个未确认计划版本及 ${impact.sources} 份来源登记。`
            : `${impact.plans} unfinished plan ${impact.plans === 1 ? 'version' : 'versions'} and ${impact.sources} source ${impact.sources === 1 ? 'registration' : 'registrations'} will be removed.`}
          {impact.wholeMedication
            ? language === 'zh'
              ? ' 这项未确认的药物登记也会被移除。'
              : ' This unconfirmed medication registration will also be removed.'
            : null}
        </p>
      ) : null}
      {error ? (
        <div className="draft-delete-error" role="alert">
          {failureMessage ? <p>{failureMessage}</p> : <ErrorNotice error={error} />}
          {onCheckResult ? (
            <button disabled={busy} onClick={onCheckResult}>
              {language === 'zh' ? '核查删除结果' : 'Check deletion result'}
            </button>
          ) : null}
          <button disabled={busy} onClick={onConfirm}>
            {t('Retry deletion')}
          </button>
        </div>
      ) : null}
      <button className="danger" disabled={busy} onClick={onConfirm}>
        {t('Confirm delete')}
      </button>
      <button disabled={busy} onClick={onCancel}>
        {t('Cancel')}
      </button>
    </BottomSheet>
  );
}
