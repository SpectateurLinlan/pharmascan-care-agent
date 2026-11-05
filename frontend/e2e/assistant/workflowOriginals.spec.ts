/** Loopback memory services, byte-identical synthetic original, no live extraction. */
import { test, expect, type Page } from '@playwright/test';
const original = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAFAAAABQCAIAAAABc2X6AAAAOnRFWHRERU1PX21ldGFkYXRhAE9SSUdJTkFMIG1ldGFkYXRhIG11c3Qgc3Vydml2ZSBieXRlIGZvciBieXRlA2RNSwAAAKFJREFUeJzt1rERgDAQxEC9mqMmqjcdOIQZi02VXHiz1qJEYiRGYiRGYiRGYiRGYtznuS/OMv+1PJzESIzESIzESIzESIzESIzESIzESIzESIzESIzESIzESIzESIzESIzESIzESIzESIzESIzESIzESIzESIzESIzESIzESIzESIzESIzESIzESIzESIzESIzESIzESIzESIzESIxfD3jbA2RsB1pn7MFNAAAAAElFTkSuQmCC',
  'base64',
);
async function open(page: Page, language: 'en' | 'zh') {
  const client = `DEMO-originals-${language}-${crypto.randomUUID()}`;
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
  const composer = page.locator('.composer-row').getByRole('textbox');
  await composer.fill(language === 'zh' ? '我想添加一种药物' : 'Add a medication');
  await composer.press('Enter');
  await page
    .getByRole('button', { name: language === 'zh' ? '拍照识别' : 'Use a photo', exact: true })
    .click();
  return client;
}
for (const language of ['en', 'zh'] as const) {
  test(`saved original survives refresh and recognition failure in ${language}`, async ({
    page,
    baseURL,
  }) => {
    expect(new URL(baseURL!).hostname).toBe('127.0.0.1');
    const client = await open(page, language);
    await page
      .locator('.composer-row input[type=file]')
      .setInputFiles({ name: 'DEMO-original.png', mimeType: 'image/png', buffer: original });
    await page
      .getByRole('button', { name: language === 'zh' ? '发送' : 'Send', exact: true })
      .click();
    await expect(
      page.getByRole('button', { name: language === 'zh' ? '查看原图 1' : 'View original 1' }),
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
      .getByRole('button', { name: language === 'zh' ? '查看原图 1' : 'View original 1' })
      .click();
    const image = page.getByAltText(language === 'zh' ? '已保存原图 1' : 'Saved original 1');
    await expect(image).toBeVisible();
    const tasks = await (
      await page.request.get(`/api/agent/workflows/tasks?client_id=${client}`)
    ).json();
    const attachments = await (
      await page.request.get(
        `/api/agent/workflows/tasks/${tasks[0].task_id}/attachments?client_id=${client}`,
      )
    ).json();
    const raw = await page.request.get(
      `/api/agent/workflows/tasks/${tasks[0].task_id}/attachments/${attachments[0].id}?client_id=${client}`,
    );
    expect(await raw.body()).toEqual(original);
    expect(raw.headers()['cache-control']).toBe('no-store');
    await page
      .getByRole('checkbox', {
        name: language === 'zh' ? '允许识别已保存的照片' : 'Allow recognition of saved photos',
      })
      .check();
    await page
      .getByRole('button', { name: language === 'zh' ? '识别已保存照片' : 'Recognize saved photo' })
      .click();
    await expect(
      page.getByText(
        language === 'zh'
          ? '暂时无法使用图片识别服务，原图仍已保存。'
          : 'Photo recognition is unavailable. The original is still saved.',
        { exact: true },
      ),
    ).toBeVisible();
    expect(
      (await (await page.request.get(`/api/me/medications?client_id=${client}`)).json())
        .medications,
    ).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    await page.screenshot({
      path: `../outputs/assistant-workflows/original-${language}.png`,
      fullPage: true,
    });
  });
}
test('no-save photo stays on page and refresh reports lost input with chat history enabled', async ({
  page,
}) => {
  const client = await open(page, 'en');
  await page.getByRole('button', { name: 'Do not save this workflow' }).click();
  await page
    .locator('.composer-row input[type=file]')
    .setInputFiles({ name: 'DEMO-private.png', mimeType: 'image/png', buffer: original });
  await page
    .getByRole('checkbox', {
      name: 'Allow photo processing. This app will not save the original; refreshing loses the page copy.',
    })
    .check();
  await page.getByRole('button', { name: 'Send', exact: true }).click();
  await expect(
    page.getByText('Page copy only. Refreshing loses this photo.', { exact: true }),
  ).toBeVisible();
  expect(await page.evaluate(() => JSON.stringify({ ...localStorage }))).not.toContain(
    'DEMO-private',
  );
  expect(
    await (await page.request.get(`/api/agent/workflows/tasks?client_id=${client}`)).json(),
  ).toEqual([]);
  await page.reload();
  await page.getByRole('button', { name: 'Unfinished tasks', exact: true }).click();
  await page.getByRole('button', { name: 'Resume task: Unsaved task', exact: true }).click();
  await expect(
    page.getByText('Page details are unavailable. Please enter them again.', { exact: true }),
  ).toBeVisible();
  await expect(page.getByText('DEMO-private.png', { exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'View original 1' })).toHaveCount(0);
});

test('lost upload response retries the same immutable original without duplicate attachments', async ({
  page,
}) => {
  const client = await open(page, 'en');
  let dropped = false;
  const keys: string[] = [];
  await page.route('**/api/agent/workflows/tasks/*/attachments/*?*', async (route) => {
    if (route.request().method() !== 'PUT') return route.continue();
    keys.push(new URL(route.request().url()).pathname);
    if (!dropped) {
      dropped = true;
      const response = await route.fetch();
      expect(response.ok()).toBe(true);
      return route.abort('failed');
    }
    return route.continue();
  });
  await page
    .locator('.composer-row input[type=file]')
    .setInputFiles({ name: 'DEMO-original.png', mimeType: 'image/png', buffer: original });
  await page.getByRole('button', { name: 'Send', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('Failed to fetch');
  await page.getByRole('button', { name: 'Dismiss', exact: true }).click();
  await page.getByRole('button', { name: 'Send', exact: true }).click();
  await expect(page.getByRole('button', { name: 'View original 1' })).toBeVisible();
  expect(keys).toHaveLength(2);
  expect(keys[0]).toBe(keys[1]);
  const tasks = await (
    await page.request.get(`/api/agent/workflows/tasks?client_id=${client}`)
  ).json();
  const attachments = await (
    await page.request.get(
      `/api/agent/workflows/tasks/${tasks[0].task_id}/attachments?client_id=${client}`,
    )
  ).json();
  expect(attachments).toHaveLength(1);
  const raw = await page.request.get(
    `/api/agent/workflows/tasks/${tasks[0].task_id}/attachments/${attachments[0].id}?client_id=${client}`,
  );
  expect(await raw.body()).toEqual(original);
});
