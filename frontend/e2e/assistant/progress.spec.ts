import { expect, test } from '@playwright/test';

for (const language of ['en', 'zh'] as const) {
  test(`DEMO_ONLY ${language} actual progress and validated final response`, async ({
    page,
    baseURL,
  }) => {
    expect(new URL(baseURL!).hostname).toBe('127.0.0.1');
    await page.setViewportSize(
      language === 'en' ? { width: 1280, height: 900 } : { width: 390, height: 844 },
    );
    const client = `DEMO-progress-${language}-${Date.now()}`;
    const session = await (
      await page.request.post('/api/demo/start', { data: { client_id: client } })
    ).json();
    await page.request.put(`/api/me/preferences?client_id=${client}`, {
      data: {
        preferred_language: language,
        conversation_history_enabled: false,
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
    let posts = 0,
      normalPosts = 0,
      runId = '';
    page.on('request', (request) => {
      if (request.url().includes('/messages/stream?')) {
        posts++;
        runId = request.postDataJSON().run_id;
      } else if (request.url().includes('/workflows/messages?')) normalPosts++;
    });
    await page.goto('/');
    const composer = page.locator('.composer-row').getByRole('textbox');
    await composer.fill(language === 'zh' ? 'DEMO 运行状态' : 'DEMO progress run');
    await composer.press('Enter');
    await expect(page.locator('.assistant-run')).toContainText(
      language === 'zh' ? '正在整理已核实的资料' : 'Preparing an answer from verified information',
    );
    await expect(
      page.getByRole('button', {
        name: language === 'zh' ? '停止处理' : 'Stop processing',
        exact: true,
      }),
    ).toBeEnabled();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    await page.screenshot({
      path: `../outputs/assistant-progress/${language}-running.png`,
      fullPage: true,
    });
    await expect(page.locator('.assistant-run')).toContainText(
      language === 'zh' ? '处理已完成' : 'Processing completed',
    );
    await expect(composer).toHaveValue('');
    const run = await (
      await page.request.get(`/api/agent/workflows/runs/${runId}?client_id=${client}`)
    ).json();
    expect(run.status).toBe('completed');
    expect(run.metadata.model_requests).toBe(2);
    expect(run.metadata.tool_calls).toBe(1);
    expect(run.metadata.provider).toBeNull();
    expect(run.metadata.sdk_attempts).toBeNull();
    expect(run.metadata.usage).toBeNull();
    expect(posts).toBe(1);
    expect(normalPosts).toBe(0);
  });
}

test('DEMO_ONLY stop waits for current step and never resends the message', async ({
  page,
  baseURL,
}) => {
  expect(new URL(baseURL!).hostname).toBe('127.0.0.1');
  const client = `DEMO-progress-cancel-${Date.now()}`;
  const session = await (
    await page.request.post('/api/demo/start', { data: { client_id: client } })
  ).json();
  await page.request.put(`/api/me/preferences?client_id=${client}`, {
    data: { preferred_language: 'en', conversation_history_enabled: false, voice_enabled: false },
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
  let posts = 0,
    runId = '';
  page.on('request', (request) => {
    if (request.url().includes('/messages/stream?')) {
      posts++;
      runId = request.postDataJSON().run_id;
    }
  });
  await page.goto('/');
  const composer = page.locator('.composer-row').getByRole('textbox');
  await composer.fill('DEMO stop processing');
  await composer.press('Enter');
  await page.getByRole('button', { name: 'Stop processing', exact: true }).click();
  await expect(page.locator('.assistant-run')).toContainText(
    'Waiting for the current step to finish',
  );
  await expect(page.locator('.assistant-run')).toContainText(
    'Processing stopped. Completed changes remain saved.',
  );
  await expect(composer).toHaveValue('DEMO stop processing');
  const run = await (
    await page.request.get(`/api/agent/workflows/runs/${runId}?client_id=${client}`)
  ).json();
  expect(run.status).toBe('cancelled');
  expect(run.metadata.tool_calls).toBe(0);
  expect(run.metadata.model_requests).toBe(1);
  await page.getByRole('button', { name: 'Send', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('Check processing status');
  expect(posts).toBe(1);
});
