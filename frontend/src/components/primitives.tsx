/** Small presentational primitives shared by the screens. */

import { useLanguage } from '../language';
import {useEffect,useState,type ReactNode} from 'react';
import {createPortal} from 'react-dom';
import { ApiError } from '../api/client';

export function Card({
  title,
  hint,
  children,
}: {
  title?: string;
  hint?: string;
  children: ReactNode;
}) {
  const {t}=useLanguage();
  return (
    <section className="card">
      {title ? <h2 className="card__title">{t(title)}</h2> : null}
      {hint ? <p className="card__hint">{t(hint)}</p> : null}
      {children}
    </section>
  );
}

/**
 * Renders a backend/network failure. The stable error code is always shown so
 * the failure cannot be mistaken for a success.
 */
export function ErrorNotice({ error }: { error: unknown }) {
  const {t}=useLanguage();const [dismissed,setDismissed]=useState(false);
  useEffect(()=>setDismissed(false),[error]);
  if(dismissed)return null;
  const close=<button aria-label={t('Dismiss')} onClick={()=>setDismissed(true)}>{t('Close')}</button>;
  if (error instanceof ApiError) {
    const safeReasons=[
      'A similar medicine is already saved. Choose the existing product or add clearer product evidence.',
      'Choose a clear, nonblank photo of one pill.',
      'Choose a valid PNG or JPEG medication source photo.',
      'The record window is too large; choose a shorter period.',
      'Complete record counts could not be verified. Please retry.',
      'Records changed during loading. Please retry.',
      'Complete records could not be verified. Please retry.',
      'This service is temporarily unavailable. Please try again.',
    ];
    const reason=error.code==='REGIMEN_OVERLAP'
      ?'There is already a plan for this medicine during these dates. Open your existing medicine to review it before adding another plan.'
      :safeReasons.includes(error.message)?error.message:'Please check your input or try again. Your records have not been confirmed by this error.';
    return createPortal(
      <div className="patient-toast patient-toast--error" role="alert">
        <strong>{t("Please review this")}</strong><p>{t(reason)}</p>{close}
      </div>,document.body
    );
  }
  const message = error instanceof Error ? error.message : String(error);
  return createPortal(
    <div className="patient-toast patient-toast--error" role="alert">
      <strong>{t("Please review this")}</strong><p>{t(message)}</p>{close}
    </div>,document.body
  );
}

/** A banner describing what in this build is simulated rather than live. */
export function SimulatedNotice({ children }: { children: ReactNode }) {
  return (
    <div className="banner">
      <strong>Demo build — parts of this are simulated</strong>
      {children}
    </div>
  );
}

export function Tag({ children, muted }: { children: ReactNode; muted?: boolean }) {
  return <span className={muted ? 'tag tag--muted' : 'tag'}>{children}</span>;
}
