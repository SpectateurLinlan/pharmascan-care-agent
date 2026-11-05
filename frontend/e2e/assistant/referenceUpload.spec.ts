/** DEMO_ONLY exact private originals, save revocation, resume and native upload recovery. */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { test, expect } from '@playwright/test';

for (const language of ['en', 'zh'] as const) {
  test(`retains original and independently adds a gallery photo in ${language}`, async ({
    page,
    baseURL,
  }) => {
    expect(new URL(baseURL!).hostname).toBe('127.0.0.1');
    expect((await (await page.request.get('/api/health')).json()).database).toBe(
      'simulated_in_memory',
    );
    if (language === 'en') await page.setViewportSize({ width: 1280, height: 900 });
    await page.route('**/*', (route) => {
      const url = new URL(route.request().url());
      return !['http:', 'https:'].includes(url.protocol) || url.hostname === '127.0.0.1'
        ? route.continue()
        : route.abort('blockedbyclient');
    });
    const client = `DEMO-reference-${crypto.randomUUID()}`,
      say = (en: string, zh: string) => (language === 'zh' ? zh : en);
    async function call(method: string, path: string, data?: unknown) {
      const response = await page.request.fetch(
        `${path}${path.includes('?') ? '&' : '?'}client_id=${client}`,
        { method, ...(data ? { data } : {}) },
      );
      expect(response.ok(), await response.text()).toBe(true);
      return response.json();
    }
    const session = await call('POST', '/api/demo/start', { client_id: client });
    await call('PUT', '/api/me/preferences', {
      preferred_language: language,
      voice_enabled: false,
      tts_autoplay: false,
    });
    const med = await call('POST', '/api/medications/drafts', {
      medication_name: 'DEMO reference medicine',
      dose_amount: 1,
      dose_unit: 'tablet',
      is_prn: true,
      food_instruction: 'DEMO reviewed instructions',
    });
    await call('POST', `/api/medications/drafts/${med.source_id}/review`, { field_ids: null });
    const summary = await call(
      'POST',
      `/api/medications/drafts/${med.regimen_id}/challenge?session_id=${session.session_id}`,
      {},
    );
    await call('POST', '/api/medications/activate', {
      regimen_id: med.regimen_id,
      ...Object.fromEntries(
        ['challenge_id', 'session_id', 'session_state', 'session_state_version'].map((key) => [
          key,
          summary[key],
        ]),
      ),
    });
    await page.addInitScript(
      ({ client, owner }) => {
        localStorage.setItem('pharmascan.client_id', client);
        localStorage.setItem(
          `pharmascan.quick-start.v4:${owner}`,
          JSON.stringify({ version: 4, status: 'skipped', step: 0 }),
        );
      },
      { client, owner: session.patient_id },
    );
    await page.goto('/');
    const panel = page.getByRole('region', {
      name: say('Current task', '当前办理任务'),
      exact: true,
    });
    let stores = 0,
      nativeAttempts = 0,
      processing = 0;
    page.on('request', (request) => {
      const path = new URL(request.url()).pathname;
      if (request.method() === 'PUT' && path.includes('/attachments/')) stores++;
      if (
        request.method() === 'POST' &&
        path === `/api/evidence/gallery/${med.medication_id}/images`
      )
        nativeAttempts++;
      if (
        request.method() === 'POST' &&
        (path.endsWith('/preview') ||
          path.includes('/visual-check') ||
          path.endsWith('/check-dose'))
      )
        processing++;
    });
    const started = page.waitForResponse(
      (response) => new URL(response.url()).pathname === '/api/agent/workflows/messages',
    );
    await page
      .locator('.composer-row')
      .getByRole('textbox')
      .fill(say('add a reference photo', '添加药物照片'));
    await page.locator('.composer-row').getByRole('textbox').press('Enter');
    const task = (await (await started).json()).workflow;
    expect(task.capability_id).toBe('gallery.photo.add');
    await panel
      .getByRole('button', {
        name: `${say('Select', '选择')}: DEMO reference medicine`,
        exact: true,
      })
      .click();
    await panel
      .getByRole('button', {
        name: say('Do not save this workflow', '不保存本次办理'),
        exact: true,
      })
      .click();
    const bytes = readFileSync(resolve('../tests/backend/fixtures/DEMO_workflow_photo.png'));
    await panel
      .locator('input[type=file]')
      .setInputFiles({ name: 'DEMO_original.png', mimeType: 'image/png', buffer: bytes });
    await panel.getByRole('combobox').selectOption('package');
    await panel.getByRole('textbox').fill('DEMO patient reference');
    await panel
      .getByRole('button', { name: say('Apply photo details', '使用照片资料'), exact: true })
      .click();
    expect(stores).toBe(0);
    expect(nativeAttempts).toBe(0);
    await panel
      .getByRole('button', { name: say('Save photo draft', '保存照片草稿'), exact: true })
      .click();
    await expect(panel).toContainText('DEMO_original.png');
    if (language === 'en') {
      let announce!: (value: { attachment: { id: string } }) => void, release!: () => void;
      const observed = new Promise<{ attachment: { id: string } }>((resolve) => {
          announce = resolve;
        }),
        gate = new Promise<void>((resolve) => {
          release = resolve;
        });
      await page.route(
        '**/api/agent/workflows/tasks/*/attachments/*?*',
        async (route) => {
          const actual = await route.fetch();
          expect(actual.ok(), await actual.text()).toBe(true);
          announce(await actual.json());
          await gate;
          await route.fulfill({ response: actual });
        },
        { times: 1 },
      );
      await panel.getByRole('button', { name: 'Save original photo', exact: true }).click();
      const old = await observed;
      await panel.getByRole('button', { name: 'Do not save this workflow', exact: true }).click();
      await expect(
        panel.getByRole('button', { name: 'Save photo draft', exact: true }),
      ).toBeVisible();
      release();
      await expect(
        panel.getByRole('button', { name: 'Save photo draft', exact: true }),
      ).toBeEnabled();
      const cleanup = await call('POST', `/api/agent/workflows/tasks/${task.task_id}/cleanup`, {});
      expect(
        cleanup.find((row: { attachment_id: string }) => row.attachment_id === old.attachment.id)
          .state,
      ).toBe('deleted');
      await expect(panel).toContainText('DEMO_original.png');
      await panel.getByRole('button', { name: 'Save photo draft', exact: true }).click();
    }
    const retained = page.waitForResponse(
      (response) =>
        response.request().method() === 'PUT' &&
        new URL(response.url()).pathname.includes('/attachments/'),
    );
    await panel
      .getByRole('button', { name: say('Save original photo', '保存原始照片'), exact: true })
      .click();
    const result = await (await retained).json();
    await expect(
      panel.getByRole('button', { name: say('Prepare photo review', '准备照片核对'), exact: true }),
    ).toBeEnabled();
    const original = await page.request.get(
      `/api/agent/workflows/tasks/${task.task_id}/attachments/${result.attachment.id}?client_id=${client}`,
    );
    expect((await original.body()).equals(bytes)).toBe(true);
    expect(processing).toBe(0);
    expect(nativeAttempts).toBe(0);
    // A reload loses the page File, so the actual authenticated saved original must supply the eventual native request.
    await page.reload();
    await page
      .getByRole('button', { name: say('Unfinished tasks', '未完成的办理'), exact: true })
      .click();
    await page
      .getByRole('region', { name: say('Unfinished tasks', '未完成的办理'), exact: true })
      .getByRole('button', { name: /DEMO reference medicine/ })
      .click();
    await expect(
      page.getByText(
        say(
          'No medication recognition was requested for this gallery original.',
          '此图库原图未请求进行药物识别。',
        ),
        { exact: true },
      ),
    ).toBeVisible();
    await panel
      .getByRole('button', { name: say('Prepare photo review', '准备照片核对'), exact: true })
      .click();
    await panel
      .getByRole('button', { name: say('Review gallery photo', '核对图库照片'), exact: true })
      .click();
    let sheet = page.getByRole('dialog');
    await sheet.getByRole('button', { name: say('Cancel', '取消'), exact: true }).click();
    expect(nativeAttempts).toBe(0);
    async function review() {
      await panel
        .getByRole('button', { name: say('Review gallery photo', '核对图库照片'), exact: true })
        .click();
      sheet = page.getByRole('dialog');
      await expect(sheet).toContainText('DEMO reference medicine');
      await sheet.getByRole('checkbox').check();
    }
    await review();
    await page.screenshot({
      path: `../outputs/assistant-workflows/reference-upload-review-${language}.png`,
      fullPage: true,
    });
    if (language === 'en') {
      await page.route(
        `**/api/evidence/gallery/${med.medication_id}/images?*`,
        (route) =>
          route.fulfill({
            status: 503,
            contentType: 'application/json',
            body: JSON.stringify({
              code: 'PROVIDER_UNAVAILABLE',
              message: 'DEMO gallery unavailable',
              rule_id: null,
            }),
          }),
        { times: 1 },
      );
      await sheet.getByRole('button', { name: 'Add photo to gallery', exact: true }).click();
      await expect(sheet.getByRole('alert')).toBeVisible();
      const afterFailure = await page.request.get(
        `/api/agent/workflows/tasks/${task.task_id}/attachments/${result.attachment.id}?client_id=${client}`,
      );
      expect((await afterFailure.body()).equals(bytes)).toBe(true);
      await sheet.getByRole('button', { name: 'Check photo result', exact: true }).click();
      await review();
      await page.route(
        `**/api/evidence/gallery/${med.medication_id}/images?*`,
        async (route) => {
          const actual = await route.fetch();
          expect(actual.ok(), await actual.text()).toBe(true);
          await route.abort('failed');
        },
        { times: 1 },
      );
      await sheet.getByRole('button', { name: 'Add photo to gallery', exact: true }).click();
      await expect(sheet.getByRole('alert')).toBeVisible();
      await sheet.getByRole('button', { name: 'Check photo result', exact: true }).click();
    } else
      await sheet
        .getByRole('button', { name: say('Add photo to gallery', '添加到图库'), exact: true })
        .click();
    await expect(panel).toContainText(
      say('The actual gallery result was checked.', '已核查实际图库保存结果。'),
    );
    const gallery = await call('GET', '/api/evidence/gallery');
    const photos = gallery.flatMap((row: { images: unknown[] }) => row.images);
    expect(photos).toHaveLength(1);
    expect(photos[0].eligibility).not.toBe('eligible');
    expect(nativeAttempts).toBe(language === 'en' ? 2 : 1);
    expect(processing).toBe(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
  });
}
