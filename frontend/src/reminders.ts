/**
 * Local dose reminder port (Session 3A item 5).
 *
 * Scope, stated honestly:
 * - this is a **local, in-tab** reminder only. It uses the browser
 *   Notification API and therefore requires the page to be open.
 * - it is NOT background push. Reliable reminders while the tab is closed need
 *   a service worker plus a server or push subscription, which this build does
 *   not have (recorded as BLOCKED / P1).
 * - permission is requested ONLY when the patient explicitly asks for reminders,
 *   never on load, and never silently.
 *
 * The port exists so the Today screen depends on an interface rather than the
 * browser globals directly, which keeps the component testable and keeps the
 * architecture clean.
 */

/** Mirrors the Notification API's own permission vocabulary exactly. */
export type ReminderSupport = 'granted' | 'denied' | 'default' | 'unsupported';

export interface ReminderPort {
  readonly kind: 'local_notification' | 'noop';
  /** Current permission state; never triggers a permission prompt. */
  support(): ReminderSupport;
  /** Ask for permission. Must only be called from a user gesture. */
  requestPermission(): Promise<ReminderSupport>;
  /** Show a local notification. Resolves false when nothing was shown. */
  notify(title: string, body: string): Promise<boolean>;
}

/** Real implementation over the browser Notification API. */
export function createBrowserReminderPort(): ReminderPort {
  return {
    kind: 'local_notification',
    support: () =>
      typeof window === 'undefined' || !('Notification' in window)
        ? 'unsupported'
        : (window.Notification.permission as ReminderSupport),
    requestPermission: async () => {
      if (typeof window === 'undefined' || !('Notification' in window)) {
        return 'unsupported';
      }
      const result = await window.Notification.requestPermission();
      return result as ReminderSupport;
    },
    notify: async (title, body) => {
      if (typeof window === 'undefined' || !('Notification' in window)) {
        return false;
      }
      if (window.Notification.permission !== 'granted') {
        return false;
      }
      new window.Notification(title, { body });
      return true;
    },
  };
}

/**
 * Fallback used where the Notification API is absent (SSR, tests, older
 * browsers). It reports unsupported rather than pretending a reminder fired.
 */
export function createNoopReminderPort(): ReminderPort {
  return {
    kind: 'noop',
    support: () => 'unsupported',
    requestPermission: async () => 'unsupported',
    notify: async () => false,
  };
}

/** Description of the reminder's real limits, shown to the patient verbatim. */
export const REMINDER_LIMITATION =
  'Reminders here work only while this page is open. Reliable reminders when the app is closed need background push, which is not available in this build.';
