/** Small presentational primitives shared by the screens. */

import { useLanguage } from '../language';
import type { ReactNode } from 'react';
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
  const {t}=useLanguage();
  if (error instanceof ApiError) {
    const safeReasons=[
      'Choose a clear, nonblank photo of one pill.',
      'Choose a valid PNG or JPEG medication source photo.',
      'The record window is too large; choose a shorter period.',
      'Complete record counts could not be verified. Please retry.',
      'Records changed during loading. Please retry.',
      'Complete records could not be verified. Please retry.',
    ];
    return (
      <div className="status status--error" role="alert">
        <strong>{t("Could not complete this request.")}</strong> {t(safeReasons.includes(error.message)?error.message:'Please check your input or try again. Your records have not been confirmed by this error.')}
        <details><summary>{t('Request details')}</summary><p>{error.code} · HTTP {error.status}</p></details>
      </div>
    );
  }
  const message = error instanceof Error ? error.message : String(error);
  return (
    <div className="status status--error" role="alert">
      <strong>{t("Something went wrong.")}</strong> {t(message)}
    </div>
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
