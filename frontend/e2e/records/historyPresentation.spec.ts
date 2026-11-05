import type { MedicationSummary, RegimenHistoryItem } from '../../src/api/client';
/** DEMO_ONLY browser regression: history service failures do not hide current medicines. */
import { expect, test } from '@playwright/test';
import { mockPatientApp } from '../support/patientAppFixture';

test('shows only an inline retry when history is unavailable, without rejected current medicines or popup', async ({
  page,
}) => {
  const { errors, setMedications } = await mockPatientApp(page);
  setMedications([
    {
      medication_id: 'DEMO-medication',
      regimen_id: 'DEMO-regimen',
      display_name: 'DEMO Amlodipine',
      dose_amount: 5,
      dose_unit: 'mg',
      is_prn: false,
      version_no: 1,
      identity_status: 'reviewed',
      source_backed: true,
    },
  ]);
  await page.route(
    (url) => new URL(url).pathname === '/api/me/medication-history/catalogue',
    (route) =>
      route.fulfill({
        status: 503,
        contentType: 'application/json',
        body: JSON.stringify({
          code: 'PROVIDER_UNAVAILABLE',
          message: 'This service is temporarily unavailable. Please try again.',
          rule_id: null,
        }),
      }),
  );
  await page.goto('/');
  await page.locator('[data-guide="records"]').click();
  await page.getByRole('button', { name: /^My medication records/ }).click();
  await expect(page.getByRole('heading', { name: 'Current medicines' })).toHaveCount(0);
  await expect(page.getByRole('alert')).toContainText(
    'Could not load medication history. Please retry.',
  );
  await expect(page.getByRole('button', { name: 'Retry history query' })).toBeVisible();
  await expect(page.getByText('Please review this')).toHaveCount(0);
  expect(errors).toEqual([]);
});

// Current stored-record presentation, sharing the same synthetic patient fixture.
test.describe('History pagination and plan scope', () => {
  const medicine = (i: number): MedicationSummary => ({
    medication_id: `DEMO-med-${i}`,
    regimen_id: `DEMO-plan-${i}`,
    display_name: `DEMO synthetic long medicine name ${i} / ${'extended name '.repeat(2)}`,
    dose_amount: 1,
    dose_unit: 'tablet',
    is_prn: false,
    version_no: 1,
    identity_status: 'user_reviewed_document',
    source_backed: true,
    frequency_rule: { kind: 'daily', local_times: ['08:00'], days_of_week: [] },
  });

  const plan: RegimenHistoryItem = {
    ...medicine(0),
    effective_from: '2026-10-01T00:00:00Z',
    effective_to: null,
    state: 'active',
    course_start_date: null,
    course_end_date: null,
    food_instruction: null,
    dose_amount: 1,
    dose_unit: 'tablet',
    local_times: ['08:00'],
  };

  test('history scope, stable plan selection, progressive records and summary actions', async ({
    page,
  }) => {
    const mock = await mockPatientApp(page);
    mock.setPlans([
      plan,
      {
        ...plan,
        regimen_id: 'DEMO-previous',
        version_no: 2,
        state: 'superseded',
        effective_from: '2026-09-01T00:00:00Z',
      },
    ]);
    for (const count of [0, 1, 5, 20]) {
      mock.setEvents(
        Array.from({ length: count }, (_, i) => ({
          occurrence_id: `DEMO-${i}`,
          due_at: new Date(Date.UTC(2026, 9, 16, 0, i)).toISOString(),
          reported: i % 4 !== 3,
          intake_status: ['reported_taken', 'reported_not_taken', 'unsure', null][i % 4]!,
          visual_status: null,
        })),
      );
      await page.goto('/e2e/support/patientApp.html?shell=1');
      await page.locator('[data-guide="records"]').click();
      await page.getByRole('button', { name: /^My medication records/ }).click();
      const history = page.locator('.record-history');
      await expect(history.locator('.history li')).toHaveCount(Math.min(5, count));
      for (let n = 5; n < count; n += 5)
        await history.getByRole('button', { name: 'Load more records' }).click();
      await expect(history.locator('.history li')).toHaveCount(count);
      await expect(history.getByRole('button', { name: 'Load more records' })).toHaveCount(0);
      await page.getByLabel('Medication plan', { exact: true }).selectOption('DEMO-previous');
      await expect(history.locator('.history li')).toHaveCount(Math.min(5, count));
    }
    for (const [label, period] of [
      ['This week', 'week'],
      ['This month', 'month'],
      ['By medication plan', 'course'],
    ]) {
      await page.locator('[data-guide="records"]').click();
      await page.getByRole('button', { name: label, exact: true }).click();
      await expect(page.getByText('Record-based report', { exact: true })).toBeVisible();
      expect(mock.reads.some((url) => new URL(url).searchParams.get('period') === period)).toBe(
        true,
      );
    }
  });
});
