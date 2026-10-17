/**
 * Shared UI primitives for the redesigned patient interface.
 *
 * These are the only components new screens should build from. They exist so a
 * safety-critical decision (is this plan reviewed? is this photo evidence?) is
 * presented the same way everywhere, instead of once per screen.
 *
 * Presentation only: no primitive fetches, stores or mutates anything.
 */

import {useLanguage} from '../language';
import {Icon, type IconName} from '../components/Icon';
import type {ReactNode} from 'react';

export type Tone = 'ok' | 'warn' | 'danger' | 'info' | 'quiet';

const toneClass = (base: string, tone: Tone) => (tone === 'quiet' ? base : `${base} ${base}--${tone}`);

/** A screen: exactly one h1, an optional lead sentence, and one primary action. */
export function Screen({title, lead, actions, children, columns = false, className}: {
  title: string;
  lead?: string | undefined;
  actions?: ReactNode | undefined;
  children?: ReactNode | undefined;
  columns?: boolean;
  className?: string | undefined;
}) {
  const {t} = useLanguage();
  return (
    <section className={`ui-screen${columns ? ' ui-screen--columns' : ''}${className ? ` ${className}` : ''}`}>
      <div className="ui-screen__head">
        <h1>{t(title)}</h1>
        {lead ? <p className="ui-screen__lead">{t(lead)}</p> : null}
      </div>
      {actions ? <div className="ui-actions">{actions}</div> : null}
      {children}
    </section>
  );
}

/** A grouped list of rows inside one panel. */
export function RowGroup({title, hint, span, spread, children}: {
  title?: string | undefined;
  hint?: string | undefined;
  /**
   * Desktop width in 12ths. Omit for the full width — the default, and what
   * every screen uses today: a single reading column is the familiar settings
   * pattern and the easiest to scan. Two genuine *peers* (two equally
   * interchangeable summaries, say) may opt into `6` so they sit side by side
   * deliberately rather than because the grid happened to have room — but that
   * is an explicit, reviewable choice, never an accident of JSX order.
   */
  span?: 4 | 6 | 8 | undefined;
  /**
   * Lay the entries out across the group's width instead of stacking them.
   * For a full-width group that is really a menu of equal destinations — not
   * for a list of medications, where each row needs the whole width.
   */
  spread?: boolean | undefined;
  children: ReactNode;
}) {
  const {t} = useLanguage();
  return (
    <section className={`card entry-group${span ? ` ui-span-${span}` : ''}${spread ? ' entry-group--spread' : ''}`}>
      {title ? <h2 className="card__title">{t(title)}</h2> : null}
      {hint ? <p className="card__hint">{t(hint)}</p> : null}
      <div className="ui-rows">{children}</div>
    </section>
  );
}

/** One navigable row. Title and hint are translated; `end` defaults to a chevron. */
export function Row({icon, title, hint, end, onClick, disabled}: {
  icon?: IconName | undefined;
  title: string;
  hint?: string | undefined;
  end?: ReactNode | undefined;
  onClick: () => void;
  disabled?: boolean | undefined;
}) {
  const {t} = useLanguage();
  return (
    <button type="button" className="ui-row" onClick={onClick} disabled={disabled}>
      {icon ? <span className="ui-row__icon"><Icon name={icon} /></span> : null}
      <span className="ui-row__text">
        <span className="ui-row__title">{t(title)}</span>
        {hint ? <span className="ui-row__hint">{t(hint)}</span> : null}
      </span>
      <span className="ui-row__end">{end ?? <Icon name="chevron-right" />}</span>
    </button>
  );
}

/**
 * Semantic status. Always carries a word and a shape as well as a colour, so it
 * survives greyscale, colour blindness and low vision.
 */
export function StatusPill({tone = 'quiet', label, icon}: {
  tone?: Tone | undefined;
  label: string;
  icon?: IconName | undefined;
}) {
  const {t} = useLanguage();
  return (
    <span className={toneClass('ui-pill', tone)}>
      {icon ? <Icon name={icon} style={{width: '1rem', height: '1rem'}} /> : null}
      {t(label)}
    </span>
  );
}

/**
 * Review and provenance state of a medication record.
 *
 * Two independent facts are reported here and never merged:
 *  - `state`          — whether this plan version has been reviewed. This gates
 *                       whether the schedule is live, so it is reported first.
 *  - `identityStatus` — whether the product itself is identified. Activation is
 *                       blocked while it is `unverified` (see backend policy), so
 *                       an active plan with an unverified identity is a
 *                       contradiction that must be surfaced, not hidden.
 * `sourceBacked` is provenance only: it never makes a plan look reviewed.
 */
export function VerificationBadge({state, sourceBacked, identityStatus}: {
  state?: string | null | undefined;
  sourceBacked?: boolean | null | undefined;
  identityStatus?: string | null | undefined;
}) {
  if (state === 'draft') return <StatusPill tone="warn" icon="alert" label="Awaiting review" />;
  if (state === 'pending_clarification') return <StatusPill tone="warn" icon="alert" label="Awaiting clarification" />;
  if (state === 'superseded') return <StatusPill tone="quiet" label="Replaced by a newer version" />;
  if (state === 'ended') return <StatusPill tone="quiet" label="Ended" />;
  if (state === 'active') {
    return identityStatus === 'unverified'
      ? <StatusPill tone="warn" icon="alert" label="Active, product not identified" />
      : <StatusPill tone="ok" icon="shield" label="Reviewed and active" />;
  }
  if (identityStatus === 'professional_verified') return <StatusPill tone="ok" icon="shield" label="Identity professionally verified" />;
  if (identityStatus === 'user_reviewed_document') return <StatusPill tone="info" icon="file" label="Identity from your document" />;
  if (sourceBacked) return <StatusPill tone="info" icon="file" label="Source-backed" />;
  return <StatusPill tone="warn" icon="alert" label="Product not identified" />;
}

/** A designed empty state: what this is, and the one action available. */
export function EmptyState({icon = 'info', title, text, action}: {
  icon?: IconName | undefined;
  title: string;
  text?: string | undefined;
  action?: ReactNode | undefined;
}) {
  const {t} = useLanguage();
  return (
    <div className="ui-empty">
      <span className="ui-empty__art"><Icon name={icon} style={{width: '3rem', height: '3rem'}} /></span>
      <p className="ui-empty__title">{t(title)}</p>
      {text ? <p className="ui-empty__text">{t(text)}</p> : null}
      {action}
    </div>
  );
}

/** An explanation the patient must be able to read, not a decoration. */
export function Callout({tone = 'info', icon, title, children}: {
  tone?: Tone | undefined;
  icon?: IconName | undefined;
  title?: string | undefined;
  children: ReactNode;
}) {
  const {t} = useLanguage();
  return (
    <div className={toneClass('ui-callout', tone)} role={tone === 'danger' || tone === 'warn' ? 'alert' : undefined}>
      {title ? <strong>{icon ? <Icon name={icon} style={{width: '1rem', height: '1rem'}} /> : null} {t(title)}</strong> : null}
      {children}
    </div>
  );
}
