/** Shared card and tag surfaces. Feedback has its own dependency boundary. */
import { useLanguage } from '../i18n/language';
import type { ReactNode } from 'react';

export { ErrorNotice, AutoDismissNotice } from './feedback';

export function Card({
  title,
  hint,
  children,
}: {
  title?: string;
  hint?: string;
  children: ReactNode;
}) {
  const { t } = useLanguage();
  return (
    <section className="card">
      {title ? <h2 className="card__title">{t(title)}</h2> : null}
      {hint ? <p className="card__hint">{t(hint)}</p> : null}
      {children}
    </section>
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
