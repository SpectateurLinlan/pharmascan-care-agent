/**
 * Tests for the local dose reminder port and the due-status wording
 * (Session 3A items 5 and 6).
 *
 * Two product rules under test:
 * 1. a due-but-unreported dose is described as "due" or "overdue in your
 *    record" — never as "missed";
 * 2. the reminder port never pretends a reminder fired, and it never requests
 *    permission on its own.
 */

import { describe, expect, it, vi } from 'vitest';
import { describeDueStatus } from './components/TodayScreen';
import {
  createBrowserReminderPort,
  createNoopReminderPort,
  REMINDER_LIMITATION,
} from './reminders';

describe('describeDueStatus', () => {
  const now = new Date('2026-10-13T17:00:00Z');

  it('describes a dose inside its grace window as due now', () => {
    const result = describeDueStatus('2026-10-13T16:45:00Z', now);
    expect(result.label).toBe('due now');
    expect(result.overdue).toBe(false);
  });

  it('describes a long-past dose as overdue in the record', () => {
    const result = describeDueStatus('2026-10-13T08:00:00Z', now);
    expect(result.label).toBe('overdue in your record');
    expect(result.overdue).toBe(true);
  });

  it('never uses the word "missed"', () => {
    for (const dueAt of ['2026-10-13T16:45:00Z', '2026-10-13T08:00:00Z']) {
      expect(describeDueStatus(dueAt, now).label).not.toContain('missed');
    }
  });

  it('falls back to due now for a missing or malformed timestamp', () => {
    expect(describeDueStatus(null, now).label).toBe('due now');
    expect(describeDueStatus('not-a-date', now).label).toBe('due now');
  });
});

describe('reminder port', () => {
  it('the noop port reports unsupported and never notifies', async () => {
    const port = createNoopReminderPort();
    expect(port.support()).toBe('unsupported');
    expect(await port.requestPermission()).toBe('unsupported');
    expect(await port.notify('t', 'b')).toBe(false);
  });

  it('states its real limitation verbatim', () => {
    expect(REMINDER_LIMITATION).toContain('only while this page is open');
    expect(REMINDER_LIMITATION).toContain('background push');
  });

  it('refuses to notify when permission is not granted', async () => {
    const original = globalThis.window;
    // Simulate a browser where notifications exist but are denied.
    vi.stubGlobal('window', {
      Notification: Object.assign(vi.fn(), { permission: 'denied' }) as unknown,
    });
    const port = createBrowserReminderPort();
    expect(port.support()).toBe('denied');
    expect(await port.notify('title', 'body')).toBe(false);
    vi.stubGlobal('window', original);
  });

  it('only reads permission on support() — it does not prompt', () => {
    const requestPermission = vi.fn().mockResolvedValue('granted');
    vi.stubGlobal('window', {
      Notification: Object.assign(vi.fn(), {
        permission: 'default',
        requestPermission,
      }) as unknown,
    });
    const port = createBrowserReminderPort();
    port.support();
    expect(requestPermission).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });
});
