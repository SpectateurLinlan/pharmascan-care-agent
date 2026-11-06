// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { api } from '../../api/client';
import { historyCatalogue, historyPage } from '../../test/fixtures/historyTestFixture';
import { MedicationRecordsScreen } from './MedicationRecordsScreen';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

it('keeps stored history and its filters available when pending report lookup fails', async () => {
  vi.spyOn(api, 'doseFollowUps').mockRejectedValue(new Error('demo read failure'));
  vi.spyOn(api, 'historyCatalogue').mockResolvedValue(historyCatalogue);
  vi.spyOn(api, 'medicationHistory').mockResolvedValue(historyPage([]));
  render(<MedicationRecordsScreen lateReportsEnabled />);
  expect(await screen.findByText('No records in this range.')).toBeTruthy();
  expect(screen.getByLabelText('Date range')).toHaveProperty('value', '30');
  expect(await screen.findByRole('button', { name: 'Retry' })).toBeTruthy();
  expect(screen.queryByText('0 doses')).toBeNull();
});

it('keeps history available without reading late reports when the capability is disabled', async () => {
  const pending = vi.spyOn(api, 'doseFollowUps');
  vi.spyOn(api, 'historyCatalogue').mockResolvedValue(historyCatalogue);
  vi.spyOn(api, 'medicationHistory').mockResolvedValue(historyPage([]));
  render(<MedicationRecordsScreen lateReportsEnabled={false} />);
  expect(await screen.findByText('No records in this range.')).toBeTruthy();
  expect(pending).not.toHaveBeenCalled();
  expect(screen.getByText(/Late reporting is not enabled yet/)).toBeTruthy();
});
