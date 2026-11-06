// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { api } from '../../api/client';
import type { DoseFollowUp, DoseFollowUps } from '../../api/doseFollowUps';
import { LateDoseFollowUps } from './LateDoseFollowUps';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
const item: DoseFollowUp = {
  occurrence_id: 'demo-occurrence',
  regimen_id: 'demo-plan',
  medication_id: 'demo-med',
  medication_name: 'DEMO medicine',
  due_at: '2026-10-19T00:00:00Z',
  dose_amount: 1,
  dose_unit: 'tablet',
  can_report: true,
  report_id: null,
  intake_status: null,
  actual_administration_at: null,
  recorded_at: null,
  reason: null,
  notes: '',
};

function response(items: DoseFollowUp[]): DoseFollowUps {
  return { items, has_more: false, timezone: 'Asia/Singapore', as_of: '2026-10-19T04:00:00Z' };
}

it('shows only a verified patient-local pending count and navigates without a duplicate reporting action', async () => {
  const unknown = { ...item, occurrence_id: 'demo-unknown' };
  delete unknown.can_report;
  vi.spyOn(api, 'doseFollowUps').mockResolvedValue(
    response([
      item,
      unknown,
      { ...item, occurrence_id: 'demo-blocked', can_report: false },
      { ...item, occurrence_id: 'demo-reported', report_id: 'demo-report' },
      { ...item, occurrence_id: 'demo-yesterday', due_at: '2026-10-18T15:00:00Z' },
    ]),
  );
  const open = vi.fn();
  render(<LateDoseFollowUps todayOnly presentation="summary" onHistory={open} />);
  const link = await screen.findByRole('button', { name: /View medication records/ });
  expect(screen.getByText('Dose reports still to add')).toBeTruthy();
  expect(screen.getByText('At least 1 dose')).toBeTruthy();
  expect(screen.queryByRole('button', { name: 'Record status' })).toBeNull();
  expect(screen.queryByText('DEMO medicine')).toBeNull();
  fireEvent.click(link);
  expect(open).toHaveBeenCalledOnce();
});

it('omits a successfully verified empty summary', async () => {
  vi.spyOn(api, 'doseFollowUps').mockResolvedValue(response([]));
  const { container } = render(<LateDoseFollowUps todayOnly presentation="summary" />);
  await waitFor(() => expect(container.textContent).toBe(''));
});

it('preserves loading and read failure without claiming a zero count', async () => {
  let reject!: (reason: Error) => void;
  vi.spyOn(api, 'doseFollowUps').mockReturnValue(
    new Promise((_, fail) => {
      reject = fail;
    }),
  );
  render(<LateDoseFollowUps todayOnly presentation="summary" />);
  expect(screen.getByRole('status').textContent).toContain('Loading');
  await waitFor(() => expect(reject).toBeDefined());
  await act(async () => reject(new Error('demo read unavailable')));
  expect(await screen.findByRole('button', { name: 'Retry' })).toBeTruthy();
  expect(screen.queryByText('0 doses')).toBeNull();
});

it('keeps unknown eligibility unavailable instead of treating an incomplete response as verified empty', async () => {
  const unknown = { ...item };
  delete unknown.can_report;
  vi.spyOn(api, 'doseFollowUps').mockResolvedValue(response([unknown]));
  render(<LateDoseFollowUps todayOnly presentation="summary" />);
  expect(
    await screen.findByText('Dose report availability could not be verified. Please retry.'),
  ).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Retry' })).toBeTruthy();
  expect(screen.queryByText('0 doses')).toBeNull();
});

it('refreshes the summary after report changes and does not retain a stale count after a failed read', async () => {
  vi.spyOn(api, 'doseFollowUps')
    .mockResolvedValueOnce(response([item]))
    .mockRejectedValueOnce(new Error('demo read failure'));
  render(<LateDoseFollowUps todayOnly presentation="summary" />);
  await screen.findByText('1 dose');
  act(() => window.dispatchEvent(new Event('pharmascan:reminder-refresh')));
  await screen.findByRole('button', { name: 'Retry' });
  expect(screen.queryByText('1 dose')).toBeNull();
  expect(screen.queryByText('0 doses')).toBeNull();
});

it('places verified pending details behind a counted disclosure while retaining report correction access', async () => {
  vi.spyOn(api, 'doseFollowUps').mockResolvedValue(response([item]));
  render(<LateDoseFollowUps presentation="disclosure" />);
  const summary = await screen.findByText('Dose reports still to add');
  const details = summary.closest('details')!;
  expect(details.open).toBe(false);
  expect(details.querySelector('summary')?.textContent).toContain('1 dose');
  fireEvent.click(summary);
  expect(details.open).toBe(true);
  expect(screen.getByRole('button', { name: 'Report dose status' })).toBeTruthy();
  expect(
    screen.getByRole('checkbox', { name: 'Include reported occurrences to review or correct' }),
  ).toBeTruthy();
});

it('hides an empty pending disclosure but leaves access to previous report corrections', async () => {
  vi.spyOn(api, 'doseFollowUps').mockResolvedValue(response([]));
  render(<LateDoseFollowUps presentation="disclosure" />);
  await screen.findByRole('checkbox', {
    name: 'Include reported occurrences to review or correct',
  });
  expect(screen.queryByText('Dose reports still to add')).toBeNull();
  expect(document.querySelector('.records-pending-disclosure')).toBeNull();
});
