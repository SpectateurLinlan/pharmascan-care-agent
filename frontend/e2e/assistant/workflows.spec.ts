/** Actual loopback app/API; memory-only DEMO data and no live providers. */
import { test, expect } from '@playwright/test';

for (const language of ['en', 'zh'] as const) {
  test(`workflow choices and explicit retention in ${language}`, async ({ page, baseURL }) => {
    expect(new URL(baseURL!).hostname).toBe('127.0.0.1');
    expect((await (await page.request.get('/api/health')).json()).database).toBe(
      'simulated_in_memory',
    );
    const client = `DEMO-workflows-${language}-${Date.now()}`;
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
    const composer = page.locator('.composer-row').getByRole('textbox');
    await composer.fill(language === 'zh' ? '我想添加一种药物' : 'Add a medication');
    await composer.press('Enter');
    const panel = page.getByRole('region', {
      name: language === 'zh' ? '当前办理任务' : 'Current task',
    });
    await panel
      .getByRole('button', { name: language === 'zh' ? '手动录入' : 'Enter manually', exact: true })
      .click();
    await expect(panel).toContainText(
      language === 'zh' ? '请继续补充缺少的资料。' : 'Continue with the remaining details.',
    );
    await panel
      .getByRole('button', {
        name: language === 'zh' ? '不保存本次办理' : 'Do not save this workflow',
      })
      .click();
    await expect(panel).toContainText(
      language === 'zh' ? '资料仅保留在当前页面' : 'Details stay on this page',
    );
    await panel
      .getByRole('button', { name: language === 'zh' ? '暂停办理' : 'Pause task', exact: true })
      .click();
    await panel
      .getByRole('button', { name: language === 'zh' ? '继续办理' : 'Resume task', exact: true })
      .click();
    await panel
      .getByRole('button', {
        name:
          language === 'zh' ? '现在保存药物并继续核对' : 'Save this medication and continue review',
      })
      .click();
    await expect(panel).toContainText(
      language === 'zh' ? '已保存办理进度。' : 'Task progress saved.',
    );
    expect(
      (await (await page.request.get(`/api/me/medications?client_id=${client}`)).json())
        .medications,
    ).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    await page.screenshot({
      path: `../outputs/assistant-workflows/${language}.png`,
      fullPage: true,
    });
  });
}

test('lost workflow message response recovers the same task after explicit retry', async ({
  page,
  baseURL,
}) => {
  expect(new URL(baseURL!).hostname).toBe('127.0.0.1');
  const client = `DEMO-workflows-retry-${Date.now()}`;
  const session = await (
    await page.request.post('/api/demo/start', { data: { client_id: client } })
  ).json();
  await page.request.put(`/api/me/preferences?client_id=${client}`, {
    data: { preferred_language: 'en', conversation_history_enabled: true, voice_enabled: false },
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
  let dropped = false;
  await page.route('**/api/agent/workflows/messages?*', async (route) => {
    if (!dropped) {
      dropped = true;
      const result = await route.fetch();
      expect(result.ok()).toBe(true);
      return route.abort('failed');
    }
    return route.continue();
  });
  await page.goto('/');
  const composer = page.locator('.composer-row').getByRole('textbox');
  await composer.fill('Add a medication');
  await composer.press('Enter');
  await expect(page.getByRole('alert')).toContainText('Failed to fetch');
  await expect(composer).toHaveValue('Add a medication');
  await page.getByRole('button', { name: 'Dismiss', exact: true }).click();
  await page.getByRole('button', { name: 'Send', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Enter manually', exact: true })).toBeVisible();
  const tasks = await (
    await page.request.get(`/api/agent/workflows/tasks?client_id=${client}`)
  ).json();
  expect(tasks).toHaveLength(1);
});
