/** DEMO_ONLY native PDF bytes, retained drafts, independent confirmation and receipt recovery. */
import { readFileSync } from 'node:fs';
import { test, expect } from '@playwright/test';

function demoPdf() {
  const stream = 'BT /F1 16 Tf 50 120 Td (DEMO ONLY - original unreviewed PDF) Tj ET';
  const objects = [
    '<</Type /Catalog /Pages 2 0 R>>',
    '<</Type /Pages /Kids [3 0 R] /Count 1>>',
    '<</Type /Page /Parent 2 0 R /MediaBox [0 0 500 200] /Resources <</Font <</F1 4 0 R>>>> /Contents 5 0 R>>',
    '<</Type /Font /Subtype /Type1 /BaseFont /Helvetica>>',
    `<</Length ${Buffer.byteLength(stream)}>>\nstream\n${stream}\nendstream`,
  ];
  let pdf = '%PDF-1.4\n';
  const offsets = [0];
  for (const [index, object] of objects.entries()) {
    offsets.push(Buffer.byteLength(pdf));
    pdf += `${index + 1} 0 obj\n${object}\nendobj\n`;
  }
  const xref = Buffer.byteLength(pdf);
  pdf += `xref\n0 6\n0000000000 65535 f \n${offsets
    .slice(1)
    .map((offset) => `${String(offset).padStart(10, '0')} 00000 n \n`)
    .join('')}trailer\n<</Size 6 /Root 1 0 R>>\nstartxref\n${xref}\n%%EOF`;
  return Buffer.from(pdf);
}

for (const language of ['en', 'zh'] as const) {
  test(`retains and independently uploads an original PDF in ${language}`, async ({
    page,
    baseURL,
  }) => {
    test.setTimeout(90000);
    page.setDefaultTimeout(15000);
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
    const client = `DEMO-pdf-${crypto.randomUUID()}`,
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
      medication_name: 'DEMO PDF medicine',
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
      writes = 0,
      processing = 0;
    page.on('request', (request) => {
      const path = new URL(request.url()).pathname;
      if (request.method() === 'PUT' && path.includes('/attachments/')) stores++;
      if (request.method() === 'POST' && path === `/api/evidence/gallery/${med.medication_id}/pdfs`)
        writes++;
      if (
        request.method() === 'POST' &&
        (path.endsWith('/preview') ||
          path.includes('/preview-image') ||
          path.includes('/visual-check'))
      )
        processing++;
    });
    const started = page.waitForResponse(
      (response) => new URL(response.url()).pathname === '/api/agent/workflows/messages',
    );
    await page
      .locator('.composer-row')
      .getByRole('textbox')
      .fill(say('upload a medication PDF', '上传药物PDF'));
    await page.locator('.composer-row').getByRole('textbox').press('Enter');
    const task = (await (await started).json()).workflow;
    expect(task.capability_id).toBe('library.pdf.add');
    await panel
      .getByRole('button', { name: `${say('Select', '选择')}: DEMO PDF medicine`, exact: true })
      .click();
    await panel
      .getByRole('button', {
        name: say('Do not save this workflow', '不保存本次办理'),
        exact: true,
      })
      .click();
    const bytes = demoPdf();
    await panel
      .getByLabel(say('Choose a PDF file', '选择 PDF 文件'), { exact: true })
      .setInputFiles({ name: 'DEMO_original.pdf', mimeType: 'application/pdf', buffer: bytes });
    await panel
      .getByRole('combobox', { name: say('Document category', '文档类别'), exact: true })
      .selectOption('prescription');
    await panel
      .getByLabel(say('Description (optional)', '说明（可选）'), { exact: true })
      .fill('DEMO retained document');
    await panel
      .getByRole('button', { name: say('Apply PDF details', '使用 PDF 资料'), exact: true })
      .click();
    expect(stores).toBe(0);
    expect(writes).toBe(0);
    await panel
      .getByRole('button', { name: say('Save PDF draft', '保存 PDF 草稿'), exact: true })
      .click();
    await expect(panel).toContainText('DEMO_original.pdf');
    const retained = page.waitForResponse(
      (response) =>
        response.request().method() === 'PUT' &&
        new URL(response.url()).pathname.includes('/attachments/'),
    );
    await panel
      .getByRole('button', { name: say('Save original PDF', '保存原始 PDF'), exact: true })
      .click();
    const result = await (await retained).json();
    await expect(
      panel.getByRole('button', { name: say('Prepare PDF review', '准备 PDF 核对'), exact: true }),
    ).toBeEnabled();
    const originalPath = `/api/agent/workflows/tasks/${task.task_id}/attachments/${result.attachment.id}?client_id=${client}`;
    const original = await page.request.get(originalPath);
    expect((await original.body()).equals(bytes)).toBe(true);
    expect(writes).toBe(0);
    expect(processing).toBe(0);
    await page.reload();
    await page
      .getByRole('button', { name: say('Unfinished tasks', '未完成的办理'), exact: true })
      .click();
    await page
      .getByRole('region', { name: say('Unfinished tasks', '未完成的办理'), exact: true })
      .getByRole('button', { name: /DEMO PDF medicine/ })
      .click();
    await page
      .getByRole('button', { name: say('View original PDF 1', '查看原始 PDF 1'), exact: true })
      .click();
    const downloadEvent = page.waitForEvent('download');
    await page
      .getByRole('link', { name: say('Download original PDF', '下载原始 PDF'), exact: true })
      .click();
    const download = await downloadEvent;
    expect(readFileSync((await download.path())!).equals(bytes)).toBe(true);
    await expect(page.locator('img[src^="blob:"]')).toHaveCount(0);
    await panel
      .getByRole('button', { name: say('Prepare PDF review', '准备 PDF 核对'), exact: true })
      .click();
    async function review() {
      await panel
        .getByRole('button', { name: say('Review PDF upload', '核对 PDF 上传'), exact: true })
        .click();
      const sheet = page.getByRole('dialog');
      await expect(sheet).toContainText('DEMO_original.pdf');
      await expect(sheet).toContainText('DEMO PDF medicine');
      return sheet;
    }
    let sheet = await review();
    await sheet.getByRole('button', { name: say('Cancel', '取消'), exact: true }).click();
    expect(writes).toBe(0);
    sheet = await review();
    await sheet.getByRole('checkbox').check();
    await page.screenshot({
      path: `../outputs/assistant-workflows/pdf-upload-review-${language}.png`,
      fullPage: true,
    });
    if (language === 'en') {
      await page.route(
        `**/api/evidence/gallery/${med.medication_id}/pdfs?*`,
        (route) =>
          route.fulfill({
            status: 503,
            contentType: 'application/json',
            body: JSON.stringify({
              code: 'PROVIDER_UNAVAILABLE',
              message: 'DEMO PDF unavailable',
              rule_id: null,
            }),
          }),
        { times: 1 },
      );
      await sheet.getByRole('button', { name: 'Add PDF to library', exact: true }).click();
      await expect(sheet.getByRole('alert')).toBeVisible();
      expect((await (await page.request.get(originalPath)).body()).equals(bytes)).toBe(true);
      await sheet.getByRole('button', { name: 'Check PDF result', exact: true }).click();
      sheet = await review();
      await sheet.getByRole('checkbox').check();
      await page.route(
        `**/api/evidence/gallery/${med.medication_id}/pdfs?*`,
        async (route) => {
          const actual = await route.fetch();
          expect(actual.ok(), await actual.text()).toBe(true);
          await route.abort('failed');
        },
        { times: 1 },
      );
      await sheet.getByRole('button', { name: 'Add PDF to library', exact: true }).click();
      await expect(sheet.getByRole('alert')).toBeVisible();
      await sheet.getByRole('button', { name: 'Check PDF result', exact: true }).click();
    } else
      await sheet
        .getByRole('button', { name: say('Add PDF to library', '添加 PDF 到资料库'), exact: true })
        .click();
    await expect(panel).toContainText(
      say('The actual PDF library result was checked.', '已核查实际 PDF 资料库保存结果。'),
    );
    const current = await call('GET', `/api/agent/workflows/tasks/${task.task_id}`);
    const saved = await page.request.get(
      `/api/evidence/library-files/${current.result_ref.id}?client_id=${client}`,
    );
    expect((await saved.body()).equals(bytes)).toBe(true);
    const catalog = await call('GET', `/api/evidence/gallery/${med.medication_id}/files`);
    expect(catalog.files.filter((file: { format: string }) => file.format === 'PDF')).toHaveLength(
      1,
    );
    expect(writes).toBe(language === 'en' ? 2 : 1);
    expect(stores).toBe(1);
    expect(processing).toBe(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
  });
}
