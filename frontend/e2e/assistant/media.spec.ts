/** DEMO_ONLY local memory services and real original-byte browser downloads. */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { test, expect } from '@playwright/test';

function demoPdf() {
  const stream = 'BT /F1 16 Tf 50 120 Td (DEMO ONLY - unreviewed document) Tj ET';
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
  test(`owned gallery and PDF read entry points in ${language}`, async ({ page, baseURL }) => {
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
    const client = `DEMO-media-${crypto.randomUUID()}`,
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
      medication_name: 'DEMO media medicine',
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
    const image = await page.request.post(
      `/api/evidence/gallery/${med.medication_id}/images?client_id=${client}&image_kind=package&source_description=DEMO%20package&reviewed=true`,
      {
        headers: { 'Content-Type': 'image/png', 'X-Stage2-Consent': 'true', 'X-Demo-Only': 'true' },
        data: readFileSync(resolve('../tests/backend/fixtures/DEMO_workflow_photo.png')),
      },
    );
    expect(image.ok(), await image.text()).toBe(true);
    const photo = (await image.json()).photo;
    const bytes = demoPdf();
    const uploaded = await page.request.post(
      `/api/evidence/gallery/${med.medication_id}/pdfs?client_id=${client}&filename=DEMO_original.pdf&description=DEMO%20unreviewed%20PDF`,
      { headers: { 'Content-Type': 'application/pdf' }, data: bytes },
    );
    expect(uploaded.ok(), await uploaded.text()).toBe(true);
    const file = (await uploaded.json()).file;
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
      }),
      composer = page.locator('.composer-row').getByRole('textbox');
    const entries: Record<string, [string, string]> = {
      'gallery.list': ['show my photo gallery', '查看我的药物图库'],
      'gallery.photo.view': ['view a medication photo', '查看药物照片'],
      'library.list': ['show medication PDFs', '查看药物PDF'],
      'library.pdf.view': ['preview a medication PDF', '预览药物PDF'],
      'library.pdf.download': ['download a medication PDF', '下载药物PDF'],
    };
    const visited = new Set<string>();
    let binaryReads = 0,
      patientWrites = 0;
    page.on('request', (request) => {
      const path = new URL(request.url()).pathname;
      if (/^\/api\/evidence\/(images|library-files)\//.test(path) && request.method() === 'GET')
        binaryReads++;
      if (request.method() !== 'GET' && path.startsWith('/api/evidence/')) patientWrites++;
    });
    async function start(id: string) {
      const phrase = entries[id]!;
      const response = page.waitForResponse(
        (row) => new URL(row.url()).pathname === '/api/agent/workflows/messages',
      );
      await composer.fill(say(phrase[0], phrase[1]));
      await composer.press('Enter');
      const actual = await response;
      expect(actual.ok(), await actual.text()).toBe(true);
      expect((await actual.json()).workflow.capability_id).toBe(id);
      visited.add(id);
    }
    const select = (text: string) =>
      panel.getByRole('button', { name: `${say('Select', '选择')}: ${text}`, exact: true }).click();
    await start('gallery.list');
    await expect(panel).toContainText('DEMO media medicine');
    await expect(panel).toContainText(say('Photos: 1', '照片: 1'));
    expect(binaryReads).toBe(0);
    await start('gallery.photo.view');
    await select('DEMO media medicine');
    await select('DEMO package');
    expect(binaryReads).toBe(0);
    await panel
      .getByRole('button', { name: say('View original photo', '查看原始照片'), exact: true })
      .click();
    await expect(panel.getByRole('img', { name: 'DEMO package' })).toBeVisible();
    expect(binaryReads).toBe(1);
    await expect
      .poll(() =>
        panel
          .getByRole('img', { name: 'DEMO package' })
          .evaluate((image) => (image as HTMLImageElement).naturalWidth),
      )
      .toBeGreaterThan(0);
    const original = await page.request.get(`/api/evidence/images/${photo.id}?client_id=${client}`);
    expect(original.ok()).toBe(true);
    expect(
      (await original.body()).subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10])),
    ).toBe(true);
    await start('library.list');
    await select('DEMO media medicine');
    await expect(panel).toContainText('DEMO_original.pdf');
    await expect(panel).toContainText(
      say('Its medication instructions have not been extracted', '尚未提取'),
    );
    expect(binaryReads).toBe(1);
    await start('library.pdf.view');
    await select('DEMO media medicine');
    await select('DEMO_original');
    expect(binaryReads).toBe(1);
    if (language === 'en') {
      await page.route(
        `**/api/evidence/library-files/${file.id}?*`,
        (route) => route.abort('failed'),
        { times: 1 },
      );
      await panel.getByRole('button', { name: 'Preview PDF', exact: true }).click();
      await expect(panel.getByRole('alert')).toContainText('Your selection is still here');
      await expect(panel).toContainText('DEMO_original.pdf');
    }
    await panel.getByRole('button', { name: say('Preview PDF', '预览 PDF'), exact: true }).click();
    await expect(panel.locator('iframe')).toBeVisible();
    expect((await panel.locator('iframe').boundingBox())!.height).toBeGreaterThan(250);
    await page.screenshot({
      path: `../outputs/assistant-workflows/media-preview-${language}.png`,
      fullPage: true,
    });
    await start('library.pdf.download');
    await select('DEMO media medicine');
    await select('DEMO_original');
    await panel
      .getByRole('button', { name: say('Prepare download', '准备下载'), exact: true })
      .click();
    const downloaded = page.waitForEvent('download');
    await panel
      .getByRole('link', { name: say('Download original', '下载原件'), exact: true })
      .click();
    const download = await downloaded;
    expect(download.suggestedFilename()).toBe('DEMO_original.pdf');
    expect(readFileSync((await download.path())!).equals(bytes)).toBe(true);
    const denied = await page.request.get(
      `/api/evidence/library-files/${file.id}?client_id=DEMO-media-foreign-${crypto.randomUUID()}`,
    );
    expect(denied.status()).toBe(404);
    expect(patientWrites).toBe(0);
    expect(visited.size).toBe(5);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
  });
}
