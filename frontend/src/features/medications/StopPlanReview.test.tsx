// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MedicationDetail } from './MedicinesHub';
import { api, type RegimenHistoryItem } from '../../api/client';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
it('keeps the original medication page stop action behind explicit patient confirmation', async () => {
  vi.spyOn(api, 'personalGallery').mockResolvedValue([]);
  vi.spyOn(api, 'medicationHistory').mockResolvedValue({
    entries: [],
    next_cursor: null,
    window_start: null,
    window_end: '2026-10-26T00:00:00Z',
    as_of: '2026-10-26T00:00:00Z',
    scope: 'stored_records_only',
    missing_plan_start: false,
  });
  const end = vi
    .spyOn(api, 'endPlan')
    .mockResolvedValue({ regimen_id: 'DEMO-plan', state: 'ended' });
  const row: RegimenHistoryItem = {
    regimen_id: 'DEMO-plan',
    medication_id: 'DEMO-med',
    display_name: 'DEMO stop baseline',
    version_no: 1,
    state: 'active',
    effective_from: null,
    effective_to: null,
    course_start_date: null,
    course_end_date: null,
    dose_amount: 1,
    dose_unit: 'tablet',
    food_instruction: null,
    is_prn: false,
    local_times: ['20:00'],
  };
  render(
    <MedicationDetail
      row={row}
      onHistory={() => undefined}
      onGallery={() => undefined}
      onCheck={() => undefined}
    />,
  );
  fireEvent.click(screen.getByRole('button', { name: 'Stop tracking this regimen' }));
  expect(end).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Confirm stop' }));
  await waitFor(() => expect(end).toHaveBeenCalledWith('DEMO-plan'));
});
