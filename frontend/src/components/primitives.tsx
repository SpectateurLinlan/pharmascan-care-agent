/** Small presentational primitives shared by the screens. */

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
  return (
    <section className="card">
      {title ? <h2 className="card__title">{title}</h2> : null}
      {hint ? <p className="card__hint">{hint}</p> : null}
      {children}
    </section>
  );
}

/**
 * Renders a backend/network failure. The stable error code is always shown so
 * the failure cannot be mistaken for a success.
 */
export function ErrorNotice({ error }: { error: unknown }) {
  if (error instanceof ApiError) {
    return (
      <div className="status status--error" role="alert">
        <strong>Request refused.</strong> {error.message}
        <span className="status__code">
          {error.code}
          {error.ruleId ? ` · rule ${error.ruleId}` : ''} · HTTP {error.status}
        </span>
      </div>
    );
  }
  const message = error instanceof Error ? error.message : String(error);
  return (
    <div className="status status--error" role="alert">
      <strong>Something went wrong.</strong> {message}
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
