/** Current App + isolated in-memory API. No SQL, provider, or notification delivery. */
import { expect, test, type Page } from '@playwright/test';
import { skipInitialGuide } from '../support/navigation';

// Preserve the explicit opt-in used by the retired local navigation journeys.
test.skip(process.env.RUN_LOCAL_UX !== '1', 'Requires the isolated local memory runtime');

async function openLocalPatient(page: Page, showGuide = false) {
  const health = await (await page.request.get('/api/health')).json();
  expect(health.database).toBe('simulated_in_memory');
  const client = `DEMO-navigation-${crypto.randomUUID()}`;
  const session = await (
    await page.request.post('/api/demo/start', {
      data: { client_id: client },
    })
  ).json();
  const preferences = await page.request.put(`/api/me/preferences?client_id=${client}`, {
    data: {
      preferred_language: 'en',
      voice_enabled: false,
      tts_autoplay: false,
      reminders_enabled: false,
    },
  });
  expect(preferences.ok()).toBe(true);
  await page.addInitScript(
    ({ client, owner, showGuide }) => {
      localStorage.setItem('pharmascan.client_id', client);
      localStorage.setItem(
        `pharmascan.quick-start.v5:${owner}`,
        JSON.stringify({ version: 5, status: showGuide ? 'in_progress' : 'skipped', step: 0 }),
      );
    },
    { client, owner: session.patient_id, showGuide },
  );
  await page.goto('/');
  if (showGuide) {
    await expect(page.locator('.onboarding-tour')).toBeVisible();
    await skipInitialGuide(page);
    await expect(page.locator('.onboarding-tour')).toHaveCount(0);
  }
  await expect(page.locator('.patient-nav button')).toHaveCount(5);
  return client;
}

test('root navigation keeps browser history bounded and retains an unfinished conversation', async ({
  page,
}) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await openLocalPatient(page, true);
  const initialLength = await page.evaluate(() => history.length);
  for (let index = 0; index < 12; index++) {
    await page
      .locator(`[data-guide="${['medicines', 'records', 'me', 'today'][index % 4]}"]`)
      .click();
  }
  expect(await page.evaluate(() => history.length)).toBe(initialLength);

  await page.getByRole('button', { name: 'Open full chat', exact: true }).click();
  const composer = page.locator('.composer-row').getByRole('textbox');
  await composer.fill('DEMO unfinished conversation');
  await page
    .locator('.conversation-workspace')
    .getByRole('button', { name: 'Back', exact: true })
    .click();
  await page.locator('[data-guide="medicines"]').click();
  await page.locator('[data-guide="today"]').click();
  await page.getByRole('button', { name: 'Open full chat', exact: true }).click();
  await expect(composer).toHaveValue('DEMO unfinished conversation');
  for (const width of [390, 768, 1280]) {
    await page.setViewportSize({ width, height: 900 });
    await expect(
      page.locator('.composer-row').getByRole('button', { name: 'Send', exact: true }),
    ).toBeInViewport();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
  }
  expect(errors).toEqual([]);
});

test('calendar export downloads current follow-ups without creating an intake report', async ({
  page,
}) => {
  const client = await openLocalPatient(page);
  const task = await page.request.post(`/api/me/care-tasks?client_id=${client}`, {
    data: {
      id: crypto.randomUUID(),
      category: 'monitoring',
      title: 'DEMO calendar follow-up',
      due_at: new Date(Date.now() + 86400000).toISOString(),
      medication_id: null,
      regimen_id: null,
      notes: 'DEMO_ONLY export fixture',
      confirmed: true,
      reminder_offsets: [0],
    },
  });
  expect(task.ok(), await task.text()).toBe(true);
  const historyPath = `/api/me/medication-history?client_id=${client}`;
  const before = await page.request.get(historyPath);
  expect(before.ok()).toBe(true);
  const previousEntries = (await before.json()).entries;
  const writes: string[] = [];
  page.on('request', (request) => {
    if (request.method() !== 'GET') writes.push(new URL(request.url()).pathname);
  });
  await page.locator('[data-guide="me"]').click();
  await page.getByRole('button', { name: /Reminders & Notifications/ }).click();
  await page.getByRole('button', { name: 'Export Calendar', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Export to Calendar', exact: true });
  await dialog.getByRole('checkbox', { name: 'Medication reminders', exact: true }).uncheck();
  const download = page.waitForEvent('download');
  await dialog.getByRole('button', { name: 'Export .ics', exact: true }).click();
  const file = await download;
  expect(file.suggestedFilename()).toBe('pharmascan-reminders.ics');
  const stream = await file.createReadStream();
  const chunks: Buffer[] = [];
  for await (const chunk of stream) chunks.push(Buffer.from(chunk));
  const content = Buffer.concat(chunks).toString('utf8');
  expect(content).toContain('BEGIN:VCALENDAR');
  expect(content).toContain('BEGIN:VEVENT');
  expect(content).toContain('END:VCALENDAR');
  expect(
    writes.filter((value) => /adherence|intake|\/prn\/report|dose.*report/.test(value)),
  ).toEqual([]);
  const after = await page.request.get(historyPath);
  expect(after.ok()).toBe(true);
  expect((await after.json()).entries).toEqual(previousEntries);
});

// Retain the unique acquisition/Back/Forward regression from the older navigation suite.
// Only the visual response is synthetic; navigation and file inputs are the real App.
test('visual result Back preserves acquisition and Forward restores evidence (visual HTTP MOCK)', async ({
  page,
}) => {
  await openLocalPatient(page);
  await page.route('**/api/evidence/check-dose*', (route) =>
    route.fulfill({
      json: {
        id: '00000000-0000-4000-a000-000000000001',
        decision: 'missing_reference',
        reason:
          'No eligible personal pill photos are available. Add a reference photo to your medication.',
        reference_ids: [],
        outcome: null,
        ingestion_proven: false,
        safe_to_take: false,
      },
    }),
  );
  await page.getByRole('button', { name: 'Compare a pill photo', exact: true }).click();
  await page.getByRole('button', { name: 'Check this dose', exact: true }).click();
  const file = page.locator('input[type=file]:visible');
  await file.setInputFiles({
    name: 'DEMO-synthetic.png',
    mimeType: 'image/png',
    buffer: Buffer.from(
      'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a1XcAAAAASUVORK5CYII=',
      'base64',
    ),
  });
  await page.getByRole('checkbox').check();
  await page.getByRole('button', { name: 'Check photo', exact: true }).click();
  await expect(
    page.getByRole('heading', { name: 'Photo check result', exact: true }),
  ).toBeVisible();
  await expect(page.getByText('Add a personal reference first', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Back', exact: true }).click();
  await expect(
    page.getByRole('heading', { name: 'Compare a pill photo', exact: true }),
  ).toBeVisible();
  // Acquisition deliberately clears the DOM input so the same file can be selected again.
  // The retained React file, preview and enabled action are the user-visible contract.
  await expect(page.getByText('DEMO-synthetic.png', { exact: true })).toBeVisible();
  await expect(page.getByAltText('Selected image preview').first()).toBeVisible();
  await expect(page.getByRole('button', { name: 'Check photo', exact: true })).toBeEnabled();
  await page.goForward();
  await expect(
    page.getByRole('heading', { name: 'Photo check result', exact: true }),
  ).toBeVisible();
  await page.goBack();
  await page.getByRole('button', { name: 'Back', exact: true }).click();
  await expect(page.locator('[data-guide="today"]')).toHaveAttribute('aria-current', 'page');
  await expect(page.getByRole('button', { name: 'Back', exact: true })).toHaveCount(0);
});
