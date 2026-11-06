/** Actual App, actual local API and DEMO_ONLY enrollment; never production. */
import { test, expect, type Page } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import path from 'node:path';
import { mockPatientApp } from '../support/patientAppFixture';

async function installRecoveryFixture(page: Page, baseURL: string, language: 'en' | 'zh') {
  expect(new URL(baseURL).hostname).toBe('127.0.0.1');
  const owner = 'DEMO-enrollment-recovery';
  await page.addInitScript(
    (owner) =>
      localStorage.setItem(
        `pharmascan.quick-start.v5:${owner}`,
        JSON.stringify({ version: 5, status: 'skipped', step: 0 }),
      ),
    owner,
  );
  const stats = { creates: 0, reviews: 0, activates: 0, regimen: 'DEMO-single-regimen' };
  let input: Record<string, unknown> = {},
    reviewed = false;
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.name));
  const draft = () => ({
    medication_id: 'DEMO-med',
    regimen_id: stats.regimen,
    source_id: 'DEMO-source',
    state: 'draft',
    version_no: 1,
    source_reviewed: reviewed,
    missing_instructions: input.dose_amount ? [] : ['dose_amount'],
    reviewable_field_ids: [],
    note: 'DEMO_ONLY',
  });
  await page.route('**/*', async (route) => {
    const request = route.request(),
      url = new URL(request.url());
    if (url.origin !== new URL(baseURL).origin) return route.abort();
    if (!url.pathname.startsWith('/api/')) return route.continue();
    let body: unknown = [];
    if (url.pathname === '/api/health')
      body = {
        status: 'ok',
        database: 'simulated_in_memory',
        runtime_contract: 'patient-ux-reminders-v1',
        late_dose_reports_enabled: true,
      };
    else if (url.pathname === '/api/me/preferences')
      body = {
        patient_id: owner,
        preferred_language: language,
        timezone: 'Asia/Singapore',
        voice_enabled: false,
        reminders_enabled: false,
        text_size: 'standard',
        conversation_history_enabled: false,
      };
    else if (url.pathname === '/api/demo/start')
      body = {
        patient_id: owner,
        session_id: 'DEMO-session',
        demo_only: true,
        seeded_medication_count: 0,
        note: 'DEMO_ONLY',
      };
    else if (url.pathname === '/api/me/medications')
      body = { medications: [], item_count: 0, note: 'DEMO_ONLY' };
    else if (url.pathname === '/api/agent/workflows/capabilities')
      body = { contract_version: 1, enabled: false, capabilities: [] };
    else if (url.pathname === '/api/agent/usage')
      body = { llm_user_turns: 0, limit: 20, next_reset_at: '2026-11-07T00:00:00+08:00' };
    else if (url.pathname === '/api/me/dose-follow-ups')
      body = {
        items: [],
        timezone: 'Asia/Singapore',
        as_of: '2026-11-06T10:00:00Z',
        has_more: false,
      };
    else if (url.pathname === '/api/medications/drafts' && request.method() === 'POST') {
      stats.creates++;
      input = request.postDataJSON();
      body = draft();
    } else if (url.pathname === '/api/medications/drafts/DEMO-single-regimen') body = draft();
    else if (url.pathname === '/api/medications/drafts/DEMO-source/review') {
      stats.reviews++;
      if (stats.reviews === 1)
        return route.fulfill({
          status: 503,
          json: {
            code: 'PROVIDER_UNAVAILABLE',
            message: 'This service is temporarily unavailable. Please try again.',
            rule_id: null,
          },
        });
      reviewed = true;
      body = { source_id: 'DEMO-source', reviewed_field_count: 5, note: 'DEMO_ONLY' };
    } else if (url.pathname === '/api/medications/drafts/DEMO-single-regimen/challenge')
      body = {
        ...draft(),
        challenge_id: 'DEMO-challenge',
        session_id: 'DEMO-session',
        session_state: 'awaiting_confirmation',
        session_state_version: 1,
        expires_at: '2099-11-06T10:10:00Z',
        summary: {
          medication_name: input.medication_name,
          dose_amount: input.dose_amount,
          dose_unit: input.dose_unit,
          is_prn: false,
          frequency: { kind: 'daily', local_times: ['08:00'], days_of_week: [] },
          course_start_date: null,
          course_end_date: null,
          version_no: 1,
          local_timezone: 'Asia/Singapore',
        },
      };
    else if (url.pathname === '/api/medications/activate') {
      expect(request.postDataJSON().regimen_id).toBe(stats.regimen);
      stats.activates++;
      body = { regimen_id: stats.regimen, state: 'active', note: 'DEMO_ONLY' };
    }
    await route.fulfill({ json: body });
  });
  return { stats, errors };
}

for (const language of ['en', 'zh'] as const) {
  test(`mock enrollment recovery reuses its draft through review failure in ${language}`, async ({
    page,
    baseURL,
  }) => {
    const { stats, errors } = await installRecoveryFixture(page, baseURL!, language);
    await page.setViewportSize({ width: language === 'en' ? 1280 : 390, height: 900 });
    try {
      await page.goto('/#manual');
      await page.locator('#med-name').fill('DEMO recovery course');
      await page.locator('#med-dose').fill('1');
      await page
        .getByRole('button', {
          name: language === 'zh' ? '核对并添加' : 'Review and add',
          exact: true,
        })
        .click();
      await page
        .getByRole('checkbox', {
          name:
            language === 'zh'
              ? '我已对照原始服用说明核对过以上内容。'
              : 'I have checked these details against my original instructions.',
          exact: true,
        })
        .check();
      const add = page.getByRole('button', {
        name: language === 'zh' ? '添加此药物' : 'Add this medication',
        exact: true,
      });
      await add.click();
      await expect(page.getByRole('alert')).toContainText(
        language === 'zh' ? '草稿已保存' : 'Your draft is saved',
      );
      expect(stats.creates).toBe(1);
      await page.getByRole('alert').getByRole('button').click();
      await add.click();
      await expect(page.getByRole('dialog')).toBeVisible();
      expect(stats.creates).toBe(1);
      expect(stats.reviews).toBe(2);
      expect(stats.activates).toBe(0);
      await page.getByRole('dialog').locator('button.primary').click();
      await expect.poll(() => stats.activates).toBe(1);
      expect(stats.creates).toBe(1);
      expect(errors).toEqual([]);
      const output = path.resolve('../internal/acceptance/enrollment-records-browser');
      mkdirSync(output, { recursive: true });
      await page.screenshot({
        path: path.join(output, `${language}-activated.png`),
        fullPage: true,
      });
    } finally {
      await page.close();
    }
  });
}

test('mock enrollment recovery saves a draft on exit once without reviewing or activating it', async ({
  page,
  baseURL,
}) => {
  const { stats, errors } = await installRecoveryFixture(page, baseURL!, 'en');
  try {
    await page.goto('/#manual');
    await page.locator('#med-name').fill('DEMO continue later');
    await page
      .locator('.patient-nav')
      .getByRole('button', { name: 'Medicines', exact: true })
      .click();
    const save = page.getByRole('button', { name: 'Save draft and leave', exact: true });
    await expect(save).toBeVisible();
    await save.dblclick();
    await expect(page.getByRole('dialog')).toHaveCount(0);
    expect(stats.creates).toBe(1);
    expect(stats.reviews).toBe(0);
    expect(stats.activates).toBe(0);
    expect(errors).toEqual([]);
  } finally {
    await page.close();
  }
});
test('Chinese enlarged enrollment form remains operable at narrow and wide widths', async ({
  page,
  baseURL,
}) => {
  expect(new URL(baseURL!).origin).toBe('http://127.0.0.1:5182');
  await mockPatientApp(page);
  await page.route(
    (url) => new URL(url).pathname.startsWith('/api/'),
    (route) => route.continue(),
  );
  const headers = { Authorization: 'Bearer DEMO.synthetic-session-token' };
  await page.request.put('/api/me/preferences', {
    headers,
    data: { preferred_language: 'zh', text_scale_percent: 150, reminders_enabled: false },
  });
  await page.goto('/');
  await page.locator('[data-guide="medicines"]').click();
  await page.getByRole('button', { name: /手动添加/ }).click();
  await expect(page.getByRole('radio', { name: '填写服用天数', exact: true })).toBeChecked();
  for (const width of [390, 430, 768, 1280]) {
    await page.setViewportSize({ width, height: 1000 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    expect(
      await page.locator('#med-time-0').evaluate((el) => el.getBoundingClientRect().width),
    ).toBeGreaterThan(150);
  }
  await page.getByRole('radio', { name: '填写最后用药日', exact: true }).check();
  await expect(page.getByLabel('最后用药日（含当天）', { exact: true })).toBeVisible();
});
test('calendar alternatives, control baselines and automatically fading enrollment success', async ({
  page,
  baseURL,
}) => {
  expect(new URL(baseURL!).origin).toBe('http://127.0.0.1:5182');
  await mockPatientApp(page);
  await page.route(
    (url) => new URL(url).pathname.startsWith('/api/'),
    (route) => route.continue(),
  );
  const headers = { Authorization: 'Bearer DEMO.synthetic-session-token' };
  await page.request.put('/api/me/preferences', {
    headers,
    data: { preferred_language: 'en', text_scale_percent: 100, reminders_enabled: false },
  });
  await page.goto('/');
  await page.locator('[data-guide="medicines"]').click();
  await page.getByRole('heading', { name: /Add medication/ }).waitFor();
  await page.getByRole('button', { name: /Add manually/ }).click();
  await page
    .getByLabel('Medication name', { exact: true })
    .fill('DEMO calendar responsive refinement');
  await page.getByLabel('Dose amount', { exact: true }).fill('1');
  await page.getByLabel('Course start date', { exact: true }).fill('2026-10-17');
  await page.getByLabel('Number of days', { exact: true }).fill('7');
  await expect(page.getByText('Last day (inclusive): 2026-10-23', { exact: true })).toBeVisible();
  await page.getByRole('radio', { name: 'Enter last day', exact: true }).check();
  await expect(page.getByLabel('Last day (inclusive)', { exact: true })).toHaveValue('2026-10-23');
  await page.getByLabel('Last day (inclusive)', { exact: true }).fill('2026-10-24');
  await expect(page.getByText('Number of days: 8', { exact: true })).toBeVisible();
  for (const width of [390, 430, 768, 1024, 1280, 1600]) {
    await page.setViewportSize({ width, height: 1000 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    if (width >= 768) {
      for (const ids of [['#med-dose', '#med-unit'], ['.course-fields input[type="date"]']]) {
        const tops = await page
          .locator(ids.join(','))
          .evaluateAll((nodes) =>
            nodes
              .filter((node) => node.getBoundingClientRect().width > 0)
              .map((node) => node.getBoundingClientRect().top),
          );
        if (tops.length > 1) expect(Math.max(...tops) - Math.min(...tops)).toBeLessThan(2);
      }
    }
    const bottom = await page
        .locator('#med-time-0')
        .evaluate((el) => el.getBoundingClientRect().bottom),
      button = await page
        .getByRole('button', { name: 'Add another time', exact: true })
        .evaluate((el) => el.getBoundingClientRect().bottom);
    if (width > 640) expect(Math.abs(bottom - button)).toBeLessThan(2);
    else {
      expect(button).toBeGreaterThan(bottom);
      expect(
        await page.locator('#med-time-0').evaluate((el) => el.getBoundingClientRect().width),
      ).toBeGreaterThan(150);
    }
    if ([390, 1280].includes(width)) {
      await page.locator('#med-time-0').blur();
      await page.evaluate(() => scrollTo(0, 0));
      await page.screenshot({ path: `../outputs/enrollment-refined-${width}.png`, fullPage: true });
    }
  }
  await page.getByRole('button', { name: 'Review and add', exact: true }).click();
  await page.getByLabel('I have checked these details against my original instructions.').check();
  await page.getByRole('button', { name: 'Add this medication', exact: true }).click();
  await page.getByRole('button', { name: 'Yes, save this medication', exact: true }).click();
  const success = page.getByText('Medication added. It now appears in your medication list.', {
    exact: true,
  });
  await expect(success).toBeVisible();
  await expect(page.locator('.patient-toast--success button')).toHaveCount(0);
  await expect(success).toHaveCount(0, { timeout: 7000 });
  const records = await page.request.get('/api/me/regimens', { headers });
  const row = (
    (await records.json()) as {
      display_name: string;
      course_start_date: string;
      course_end_date: string;
    }[]
  ).find((row) => row.display_name === 'DEMO calendar responsive refinement');
  expect(row?.course_start_date).toBe('2026-10-17');
  expect(row?.course_end_date).toBe('2026-10-24');
});
