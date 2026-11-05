/** DEMO_ONLY native memory settings/contact CRUD; real Auth/email is disabled. */
import { test, expect } from '@playwright/test';

for (const language of ['en', 'zh'] as const) {
  test(`completes preferences contacts and secure-account entries in ${language}`, async ({
    page,
    baseURL,
  }) => {
    test.setTimeout(150000);
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
    let currentLanguage: 'en' | 'zh' = language;
    const say = (en: string, zh: string) => (currentLanguage === 'zh' ? zh : en),
      client = `DEMO-settings-${crypto.randomUUID()}`;
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
    let nativePreferences = 0,
      nativeContacts = 0,
      unrelated = 0;
    const workflowBodies: string[] = [];
    page.on('request', (request) => {
      const path = new URL(request.url()).pathname;
      if (path === '/api/me/preferences' && request.method() === 'PUT') nativePreferences++;
      if (path.startsWith('/api/me/caregivers') && request.method() !== 'GET') nativeContacts++;
      if (
        request.method() !== 'GET' &&
        /^\/api\/(medications|doses|prn|sources|reminders\/push)/.test(path)
      )
        unrelated++;
      if (path.includes('/api/agent/workflows')) workflowBodies.push(request.postData() ?? '');
    });
    await page.goto('/'); // Resolve the task panel after each language change.
    const currentPanel = () =>
      page.getByRole('region', { name: say('Current task', '当前办理任务'), exact: true });
    async function send(en: string, zh: string) {
      const response = page.waitForResponse(
        (row) => new URL(row.url()).pathname === '/api/agent/workflows/messages',
      );
      await page.locator('.composer-row').getByRole('textbox').fill(say(en, zh));
      await page.locator('.composer-row').getByRole('textbox').press('Enter');
      return (await (await response).json()).workflow;
    }
    async function apply() {
      await currentPanel()
        .getByRole('button', { name: say('Apply settings details', '使用设置资料'), exact: true })
        .click();
      await currentPanel()
        .getByRole('button', { name: say('Prepare settings review', '准备设置核对'), exact: true })
        .click();
      await currentPanel()
        .getByRole('button', { name: say('Review settings change', '核对设置变更'), exact: true })
        .click();
    }
    async function confirm() {
      await page
        .getByRole('dialog')
        .getByRole('button', { name: say('Confirm settings change', '确认设置变更'), exact: true })
        .click();
      await expect(currentPanel()).toContainText(
        say(
          'The earlier change was saved. Current values are shown below.',
          '此前的变更已保存，以下显示当前资料。',
        ),
      );
    }
    await send('change text size', '修改字号');
    await currentPanel().getByRole('slider').press('Home');
    for (let index = 0; index < 25; index++)
      await currentPanel().getByRole('slider').press('ArrowRight');
    expect(nativePreferences).toBe(0);
    await apply();
    await page
      .getByRole('dialog')
      .getByRole('button', { name: say('Cancel', '取消'), exact: true })
      .click();
    expect(nativePreferences).toBe(0);
    await currentPanel()
      .getByRole('button', { name: say('Review settings change', '核对设置变更'), exact: true })
      .click();
    await confirm();
    expect((await call('GET', '/api/me/preferences')).text_scale_percent).toBe(125);
    await send('change voice preferences', '修改语音偏好');
    await apply();
    await confirm();
    await send('change reminder preferences', '修改提醒偏好');
    await currentPanel()
      .getByRole('checkbox', { name: say('Medication reminders', '药物提醒'), exact: true })
      .uncheck();
    await currentPanel().getByRole('combobox').selectOption('30');
    await apply();
    await confirm();
    await send('change chat saving', '修改聊天保存设置');
    await currentPanel()
      .getByRole('checkbox', { name: say('Save chat history', '保存聊天记录'), exact: true })
      .check();
    await apply();
    await confirm();
    await send('change timezone', '修改时区');
    await currentPanel()
      .getByRole('textbox', { name: say('Time zone', '时区'), exact: true })
      .fill('America/New_York');
    await apply();
    await page.screenshot({
      path: `../outputs/assistant-workflows/settings-timezone-${language}.png`,
      fullPage: true,
    });
    await confirm();
    expect((await call('GET', '/api/me/preferences')).timezone).toBe('America/New_York');
    await send('edit my profile', '修改个人资料');
    await currentPanel()
      .getByRole('textbox', { name: say('Display name', '显示名称'), exact: true })
      .fill('DEMO profile name');
    await apply();
    await confirm();
    await send('change language', '修改语言');
    const nextLanguage = language === 'en' ? 'zh' : 'en';
    await currentPanel().getByRole('combobox').selectOption(nextLanguage);
    await apply();
    await page
      .getByRole('dialog')
      .getByRole('button', { name: say('Confirm settings change', '确认设置变更'), exact: true })
      .click();
    currentLanguage = nextLanguage;
    await expect(currentPanel()).toContainText(
      say(
        'The earlier change was saved. Current values are shown below.',
        '此前的变更已保存，以下显示当前资料。',
      ),
    );
    expect(nativePreferences).toBe(7);
    await send('show my profile', '查看个人资料');
    await expect(currentPanel()).toContainText('DEMO profile name');
    await send('add care contact', '添加关怀联系人');
    await currentPanel()
      .getByRole('textbox', { name: say('Contact name', '联系人姓名'), exact: true })
      .fill('DEMO care contact');
    await currentPanel()
      .getByRole('textbox', { name: say('Email address', '电子邮箱地址'), exact: true })
      .fill('demo.contact@example.invalid');
    await expect(
      currentPanel().getByRole('button', {
        name: say('Apply settings details', '使用设置资料'),
        exact: true,
      }),
    ).toBeDisabled();
    expect(workflowBodies.join('')).not.toContain('demo.contact@example.invalid');
    await currentPanel().getByRole('checkbox').check();
    await apply();
    await page.screenshot({
      path: `../outputs/assistant-workflows/settings-contact-${language}.png`,
      fullPage: true,
    });
    await page.route(
      '**/api/me/caregivers?*',
      (route) =>
        route.request().method() === 'POST'
          ? route.fulfill({
              status: 503,
              contentType: 'application/json',
              body: JSON.stringify({
                code: 'PROVIDER_UNAVAILABLE',
                message: 'DEMO contact save failed',
                rule_id: null,
              }),
            })
          : route.continue(),
      { times: 1 },
    );
    await page
      .getByRole('dialog')
      .getByRole('button', { name: say('Confirm settings change', '确认设置变更'), exact: true })
      .click();
    await expect(page.getByRole('dialog').getByRole('alert')).toBeVisible();
    await page
      .getByRole('dialog')
      .getByRole('button', { name: say('Check settings result', '核查设置结果'), exact: true })
      .click();
    await currentPanel()
      .getByRole('button', { name: say('Edit settings details', '修改设置资料'), exact: true })
      .click();
    await apply();
    await confirm();
    let rows = await call('GET', '/api/me/caregivers');
    expect(rows.length).toBe(1);
    expect(rows[0].notifications_enabled).toBe(false);
    expect(rows[0].sharing_enabled).toBe(false);
    await send('show care contacts', '查看关怀联系人');
    await expect(currentPanel()).toContainText('demo.contact@example.invalid');
    await send('edit care contact', '修改关怀联系人');
    await currentPanel()
      .getByRole('button', { name: /DEMO care contact/ })
      .click();
    await currentPanel()
      .getByRole('textbox', { name: say('Contact name', '联系人姓名'), exact: true })
      .fill('DEMO updated contact');
    await currentPanel().getByRole('checkbox').check();
    await apply();
    await confirm();
    await send('remove care contact', '删除关怀联系人');
    await currentPanel()
      .getByRole('button', { name: /DEMO updated contact/ })
      .click();
    await apply();
    await confirm();
    rows = await call('GET', '/api/me/caregivers');
    expect(rows).toEqual([]);
    expect(nativeContacts).toBe(4);
    for (const [en, zh] of [
      ['show account status', '查看账户状态'],
      ['sign in to my account', '登录账户'],
      ['link my email', '关联邮箱'],
      ['change my password', '修改账户密码'],
      ['sign out of my account', '退出账户'],
    ]) {
      await send(en!, zh!);
      await currentPanel()
        .getByRole('button', {
          name: say('Open secure account form', '打开安全账户表单'),
          exact: true,
        })
        .click();
      await expect(currentPanel()).toContainText(
        say('Email sign-in and account linking are unavailable in this local demo.', '本地演示'),
      );
      await currentPanel()
        .getByRole('button', { name: say('Close account form', '关闭账户表单'), exact: true })
        .click();
    }
    expect(unrelated).toBe(0);
    expect(workflowBodies.join('')).not.toMatch(/DEMO-password-secret|access_token|refresh_token/);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
  });
}
