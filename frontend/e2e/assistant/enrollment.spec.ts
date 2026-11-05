/** Real loopback app/API, synthetic owners, no model or clinical activation. */
import { test, expect, type Page } from '@playwright/test';
import { readFileSync } from 'node:fs';
const syntheticPhoto = readFileSync(
  new URL('../../../tests/backend/fixtures/DEMO_workflow_photo.png', import.meta.url),
);
const unavailablePhoto = readFileSync(
  new URL('../../../tests/backend/fixtures/DEMO_workflow_photo_unavailable.png', import.meta.url),
);

async function open(page: Page, language: 'en' | 'zh') {
  const client = `DEMO-enrollment-${language}-${crypto.randomUUID()}`;
  expect((await (await page.request.get('/api/health')).json()).database).toBe(
    'simulated_in_memory',
  );
  const session = await (
    await page.request.post('/api/demo/start', { data: { client_id: client } })
  ).json();
  await page.request.put(`/api/me/preferences?client_id=${client}`, {
    data: {
      preferred_language: language,
      conversation_history_enabled: true,
      voice_enabled: false,
      tts_autoplay: false,
    },
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
  return client;
}
for (const language of ['en', 'zh'] as const) {
  test(`manual collection asks for missing times and preserves source strength in ${language}`, async ({
    page,
    baseURL,
  }) => {
    expect(new URL(baseURL!).hostname).toBe('127.0.0.1');
    const client = await open(page, language);
    const composer = page.locator('.composer-row').getByRole('textbox');
    await composer.fill(language === 'zh' ? '我想添加一种药物' : 'Add a medication');
    await composer.press('Enter');
    const panel = page.getByRole('region', {
      name: language === 'zh' ? '当前办理任务' : 'Current task',
    });
    await panel
      .getByRole('button', { name: language === 'zh' ? '手动录入' : 'Enter manually', exact: true })
      .click();
    await composer.fill(
      language === 'zh'
        ? '药名：DEMO ibuprofen；规格：200mg；每次1片；每天2次'
        : 'name: DEMO ibuprofen; strength: 200mg; dose: 1 tablet; twice daily',
    );
    await composer.press('Enter');
    const form = panel.getByRole('form', {
      name: language === 'zh' ? '药物资料' : 'Medication details',
    });
    await expect(
      form.getByRole('spinbutton', {
        name: language === 'zh' ? '说明中写明的每日次数' : 'Recorded times per day',
      }),
    ).toHaveValue('2');
    await form.locator('input[type=time]').first().fill('08:00');
    await form.locator('.time-input-row .icon-button').first().click();
    await form.locator('input[type=time]').nth(1).fill('20:00');
    await form
      .getByRole('button', {
        name: language === 'zh' ? '使用这些资料继续' : 'Use these details',
        exact: true,
      })
      .click();
    await expect(panel).toContainText(
      language === 'zh'
        ? '请对照原始用药说明核对这些资料。'
        : 'Check these details against your original instructions.',
    );
    const tasks = await (
      await page.request.get(`/api/agent/workflows/tasks?client_id=${client}`)
    ).json();
    expect(tasks).toHaveLength(1);
    expect(tasks[0].state).toBe('ready_for_review');
    expect(tasks[0].visible_fields).toMatchObject({
      medication_name: 'DEMO ibuprofen',
      dose_amount: 1,
      dose_unit: 'tablet',
      dose_basis: { strength_text: '200mg', patient_checked: false },
      frequency_rule: { kind: 'daily', local_times: ['08:00', '20:00'] },
    });
    expect(
      (await (await page.request.get(`/api/me/medications?client_id=${client}`)).json())
        .medications,
    ).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    await page.screenshot({
      path: `../outputs/assistant-workflows/enrollment-collection-${language}.png`,
      fullPage: true,
    });
    let duplicateCreates = 0;
    page.on('request', (request) => {
      if (
        request.method() === 'POST' &&
        new URL(request.url()).pathname === '/api/medications/drafts'
      )
        duplicateCreates++;
    });
    await panel
      .getByRole('button', {
        name: language === 'zh' ? '核对这项药物' : 'Review this medication',
        exact: true,
      })
      .click();
    await expect(panel.getByText('200mg', { exact: true })).toBeVisible();
    const add = panel.getByRole('button', {
      name: language === 'zh' ? '添加此药物' : 'Add this medication',
      exact: true,
    });
    await expect(add).toBeDisabled();
    await panel
      .getByRole('checkbox', {
        name:
          language === 'zh'
            ? '我已对照原始服用说明核对过以上内容。'
            : 'I have checked these details against my original instructions.',
      })
      .check();
    await add.click();
    await page
      .getByRole('button', {
        name: language === 'zh' ? '确认：激活此用药计划' : 'Yes, save this medication',
        exact: true,
      })
      .click();
    await expect(panel).toContainText(
      language === 'zh' ? '药物计划已启用。' : 'The medication plan is active.',
    );
    const active = await (await page.request.get(`/api/me/medications?client_id=${client}`)).json();
    expect(active.medications).toHaveLength(1);
    expect(active.medications[0].display_name).toBe('DEMO ibuprofen');
    const regimens = await (await page.request.get(`/api/me/regimens?client_id=${client}`)).json();
    expect(regimens).toHaveLength(1);
    expect(regimens[0].state).toBe('active');
    expect(duplicateCreates).toBe(0);
    await page.screenshot({
      path: `../outputs/assistant-workflows/enrollment-active-${language}.png`,
      fullPage: true,
    });
  });
  test(`photo replay collects missing times and reaches independent activation in ${language}`, async ({
    page,
    baseURL,
  }) => {
    expect(new URL(baseURL!).hostname).toBe('127.0.0.1');
    const client = await open(page, language);
    const composer = page.locator('.composer-row').getByRole('textbox');
    await composer.fill(language === 'zh' ? '我想添加一种药物' : 'Add a medication');
    await composer.press('Enter');
    const panel = page.getByRole('region', {
      name: language === 'zh' ? '当前办理任务' : 'Current task',
    });
    await panel
      .getByRole('button', { name: language === 'zh' ? '拍照识别' : 'Use a photo', exact: true })
      .click();
    await page
      .locator('.composer-row input[type=file]')
      .setInputFiles({ name: 'DEMO-replay.png', mimeType: 'image/png', buffer: syntheticPhoto });
    await page
      .getByRole('button', { name: language === 'zh' ? '发送' : 'Send', exact: true })
      .click();
    await page
      .getByRole('checkbox', {
        name: language === 'zh' ? '允许识别已保存的照片' : 'Allow recognition of saved photos',
      })
      .check();
    await page
      .getByRole('button', {
        name: language === 'zh' ? '识别已保存照片' : 'Recognize saved photo',
        exact: true,
      })
      .click();
    const form = panel.getByRole('form', {
      name: language === 'zh' ? '药物资料' : 'Medication details',
    });
    await expect(
      form.getByRole('spinbutton', {
        name: language === 'zh' ? '说明中写明的每日次数' : 'Recorded times per day',
      }),
    ).toHaveValue('2');
    await form.locator('input[type=time]').first().fill('08:00');
    await form.locator('.time-input-row .icon-button').first().click();
    await form.locator('input[type=time]').nth(1).fill('20:00');
    await form
      .getByRole('button', {
        name: language === 'zh' ? '使用这些资料继续' : 'Use these details',
        exact: true,
      })
      .click();
    const tasks = await (
      await page.request.get(`/api/agent/workflows/tasks?client_id=${client}`)
    ).json();
    const taskId = tasks[0].task_id;
    await panel
      .getByRole('button', {
        name: language === 'zh' ? '核对这项药物' : 'Review this medication',
        exact: true,
      })
      .click();
    await panel
      .getByRole('checkbox', {
        name:
          language === 'zh'
            ? '我已对照原始服用说明核对过以上内容。'
            : 'I have checked these details against my original instructions.',
      })
      .check();
    await panel
      .getByRole('button', {
        name: language === 'zh' ? '添加此药物' : 'Add this medication',
        exact: true,
      })
      .click();
    await page
      .getByRole('button', {
        name: language === 'zh' ? '确认：激活此用药计划' : 'Yes, save this medication',
        exact: true,
      })
      .click();
    await expect(panel).toContainText(
      language === 'zh' ? '药物计划已启用。' : 'The medication plan is active.',
    );
    const rows = await (await page.request.get(`/api/me/regimens?client_id=${client}`)).json();
    expect(rows).toHaveLength(1);
    expect(rows[0].state).toBe('active');
    const originals = await (
      await page.request.get(`/api/agent/workflows/tasks/${taskId}/attachments?client_id=${client}`)
    ).json();
    const raw = await page.request.get(
      `/api/agent/workflows/tasks/${taskId}/attachments/${originals[0].id}?client_id=${client}`,
    );
    expect(await raw.body()).toEqual(syntheticPhoto);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    await page.screenshot({
      path: `../outputs/assistant-workflows/enrollment-photo-${language}.png`,
      fullPage: true,
    });
  });
  test(`failed photo survives refresh and switches to manual completion in ${language}`, async ({
    page,
  }) => {
    const client = await open(page, language);
    const composer = page.locator('.composer-row').getByRole('textbox');
    await composer.fill(language === 'zh' ? '我想添加一种药物' : 'Add a medication');
    await composer.press('Enter');
    await page
      .getByRole('button', { name: language === 'zh' ? '拍照识别' : 'Use a photo', exact: true })
      .click();
    await page.locator('.composer-row input[type=file]').setInputFiles({
      name: 'DEMO-unavailable.png',
      mimeType: 'image/png',
      buffer: unavailablePhoto,
    });
    await page
      .getByRole('button', { name: language === 'zh' ? '发送' : 'Send', exact: true })
      .click();
    await page
      .getByRole('checkbox', {
        name: language === 'zh' ? '允许识别已保存的照片' : 'Allow recognition of saved photos',
      })
      .check();
    await page
      .getByRole('button', {
        name: language === 'zh' ? '识别已保存照片' : 'Recognize saved photo',
        exact: true,
      })
      .click();
    await expect(
      page.getByText(
        language === 'zh'
          ? '暂时无法使用图片识别服务，原图仍已保存。'
          : 'Photo recognition is unavailable. The original is still saved.',
        { exact: true },
      ),
    ).toBeVisible();
    await page.reload();
    await page
      .getByRole('button', {
        name: language === 'zh' ? '未完成的办理' : 'Unfinished tasks',
        exact: true,
      })
      .click();
    await page
      .getByRole('button', {
        name: language === 'zh' ? '继续办理: 已保存的办理' : 'Resume task: Saved task',
        exact: true,
      })
      .click();
    await page
      .getByRole('button', {
        name: language === 'zh' ? '改为手动录入' : 'Switch to manual entry',
        exact: true,
      })
      .click();
    const input = page.locator('.composer-row').getByRole('textbox');
    await input.fill(
      language === 'zh'
        ? '药名：DEMO recovered；每次1片；每天1次；08:00'
        : 'name: DEMO recovered; dose: 1 tablet; once daily; 08:00',
    );
    await input.press('Enter');
    await page
      .getByRole('button', {
        name: language === 'zh' ? '核对这项药物' : 'Review this medication',
        exact: true,
      })
      .click();
    await page
      .getByRole('checkbox', {
        name:
          language === 'zh'
            ? '我已对照原始服用说明核对过以上内容。'
            : 'I have checked these details against my original instructions.',
      })
      .check();
    await page
      .getByRole('button', {
        name: language === 'zh' ? '添加此药物' : 'Add this medication',
        exact: true,
      })
      .click();
    await page
      .getByRole('button', {
        name: language === 'zh' ? '确认：激活此用药计划' : 'Yes, save this medication',
        exact: true,
      })
      .click();
    await expect(
      page.getByText(language === 'zh' ? '药物计划已启用。' : 'The medication plan is active.', {
        exact: true,
      }),
    ).toBeVisible();
    const tasks = await (
      await page.request.get(`/api/agent/workflows/tasks?client_id=${client}`)
    ).json();
    const originals = await (
      await page.request.get(
        `/api/agent/workflows/tasks/${tasks[0].task_id}/attachments?client_id=${client}`,
      )
    ).json();
    const raw = await page.request.get(
      `/api/agent/workflows/tasks/${tasks[0].task_id}/attachments/${originals[0].id}?client_id=${client}`,
    );
    expect(await raw.body()).toEqual(unavailablePhoto);
  });
  test(`successful no-save recognition stays page-only and reports refresh loss in ${language}`, async ({
    page,
  }) => {
    const client = await open(page, language);
    const composer = page.locator('.composer-row').getByRole('textbox');
    await composer.fill(language === 'zh' ? '我想添加一种药物' : 'Add a medication');
    await composer.press('Enter');
    await page
      .getByRole('button', { name: language === 'zh' ? '拍照识别' : 'Use a photo', exact: true })
      .click();
    await page
      .getByRole('button', {
        name: language === 'zh' ? '不保存本次办理' : 'Do not save this workflow',
        exact: true,
      })
      .click();
    await page
      .locator('.composer-row input[type=file]')
      .setInputFiles({ name: 'DEMO-page-only.png', mimeType: 'image/png', buffer: syntheticPhoto });
    await page
      .getByRole('checkbox', {
        name:
          language === 'zh'
            ? '允许处理这张照片。本应用不保存原图，刷新后将丢失页面上的原图。'
            : 'Allow photo processing. This app will not save the original; refreshing loses the page copy.',
      })
      .check();
    await page
      .getByRole('button', { name: language === 'zh' ? '发送' : 'Send', exact: true })
      .click();
    await expect(
      page
        .getByRole('form', { name: language === 'zh' ? '药物资料' : 'Medication details' })
        .getByRole('spinbutton', {
          name: language === 'zh' ? '说明中写明的每日次数' : 'Recorded times per day',
        }),
    ).toHaveValue('2');
    expect(
      (await (await page.request.get(`/api/me/medications?client_id=${client}`)).json())
        .medications,
    ).toEqual([]);
    expect(JSON.stringify(await page.evaluate(() => ({ ...localStorage })))).not.toContain(
      'DEMO Photo medicine',
    );
    expect(
      await (await page.request.get(`/api/agent/workflows/tasks?client_id=${client}`)).json(),
    ).toEqual([]);
    await page.reload();
    await page
      .getByRole('button', {
        name: language === 'zh' ? '未完成的办理' : 'Unfinished tasks',
        exact: true,
      })
      .click();
    await page
      .getByRole('button', {
        name: language === 'zh' ? '继续办理: 未保存的办理' : 'Resume task: Unsaved task',
        exact: true,
      })
      .click();
    await expect(
      page.getByText(
        language === 'zh'
          ? '当前页面资料已丢失，请重新输入。'
          : 'Page details are unavailable. Please enter them again.',
        { exact: true },
      ),
    ).toBeVisible();
  });
  test(`same name with a different recorded strength requires a separate-product choice in ${language}`, async ({
    page,
  }) => {
    const client = await open(page, language);
    const seeded = await page.request.post(`/api/medications/drafts?client_id=${client}`, {
      data: {
        medication_name: 'DEMO strength choice',
        dose_amount: 1,
        dose_unit: 'tablet',
        frequency_kind: 'daily',
        frequency_local_times: ['08:00'],
        dose_basis: { strength_text: '400 mg' },
      },
    });
    expect(seeded.ok()).toBe(true);
    const composer = page.locator('.composer-row').getByRole('textbox');
    await composer.fill(language === 'zh' ? '我想添加一种药物' : 'Add a medication');
    await composer.press('Enter');
    await page
      .getByRole('button', { name: language === 'zh' ? '手动录入' : 'Enter manually', exact: true })
      .click();
    await composer.fill(
      language === 'zh'
        ? '药名：DEMO strength choice；规格：200mg；每次1片；每天1次；08:00'
        : 'name: DEMO strength choice; strength: 200mg; dose: 1 tablet; once daily; 08:00',
    );
    await composer.press('Enter');
    await expect(page.getByRole('button', { name: /400 mg/ })).toBeVisible();
    await page
      .getByRole('button', {
        name:
          language === 'zh'
            ? '按这份不同规格的原始记录另行登记'
            : 'Register a separate product with this different recorded strength',
        exact: true,
      })
      .click();
    await page
      .getByRole('button', {
        name: language === 'zh' ? '核对这项药物' : 'Review this medication',
        exact: true,
      })
      .click();
    await expect(page.getByText('200mg', { exact: true })).toBeVisible();
    const rows = await (await page.request.get(`/api/me/regimens?client_id=${client}`)).json();
    expect(rows).toHaveLength(2);
    expect(new Set(rows.map((row: { medication_id: string }) => row.medication_id)).size).toBe(2);
    expect(rows.every((row: { state: string }) => row.state === 'draft')).toBe(true);
  });
}
