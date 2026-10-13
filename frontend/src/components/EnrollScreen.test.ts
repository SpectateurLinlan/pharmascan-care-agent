/**
 * Tests for the multi-time enrollment helper (Session 3A item 1).
 *
 * The UI gap this covers: enrollment previously allowed exactly one daily time,
 * so a twice-daily medicine could not be entered. The helper is the single
 * place that canonicalises and de-duplicates times, mirroring the backend's
 * `_normalise_local_time` so the client and server agree on what counts as the
 * same dose slot.
 */

import { describe, expect, it } from 'vitest';
import { normaliseTime } from '../components/EnrollScreen';

describe('normaliseTime', () => {
  it('keeps a well-formed HH:MM value unchanged', () => {
    expect(normaliseTime('08:00')).toBe('08:00');
    expect(normaliseTime('20:30')).toBe('20:30');
  });

  it('pads a single-digit hour', () => {
    expect(normaliseTime('8:00')).toBe('08:00');
  });

  it('collapses two spellings of the same time to one canonical value', () => {
    expect(normaliseTime('8:00')).toBe(normaliseTime('08:00'));
  });

  it('rejects malformed or out-of-range values instead of guessing', () => {
    expect(normaliseTime('')).toBe('');
    expect(normaliseTime('not a time')).toBe('');
    expect(normaliseTime('25:00')).toBe('');
    expect(normaliseTime('08:75')).toBe('');
  });

  it('distinguishes two genuinely different daily times', () => {
    expect(normaliseTime('08:00')).not.toBe(normaliseTime('20:00'));
  });
});

describe('multi-time selection', () => {
  it('de-duplicates normalised times and sorts them', () => {
    const raw = ['20:00', '8:00', '08:00'];
    const cleaned = Array.from(
      new Set(raw.map((value) => normaliseTime(value)).filter((value) => value !== '')),
    ).sort();
    // Three inputs, two real dose slots.
    expect(cleaned).toEqual(['08:00', '20:00']);
  });

  it('surfaces a twice-daily schedule as two distinct slots', () => {
    const raw = ['08:00', '20:00'];
    const cleaned = Array.from(
      new Set(raw.map((value) => normaliseTime(value)).filter((value) => value !== '')),
    ).sort();
    expect(cleaned).toHaveLength(2);
  });
});
