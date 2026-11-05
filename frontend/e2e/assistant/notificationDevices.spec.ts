/** DEMO_ONLY native memory APIs and fake browser PushManager. No OS permission or delivery. */
import { test, expect } from '@playwright/test';

for (const language of ['en', 'zh'] as const) {
  test(`handles all three notification entries with independent confirmation in ${language}`, async ({
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
    const client = `DEMO-notification-${crypto.randomUUID()}`,
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
    await page.addInitScript(
      ({ client, owner }) => {
        localStorage.setItem('pharmascan.client_id', client);
        localStorage.setItem(
          `pharmascan.quick-start.v4:${owner}`,
          JSON.stringify({ version: 4, status: 'skipped', step: 0 }),
        );
        const metrics = { permissions: 0, subscribes: 0, unsubscribes: 0 };
        Object.assign(window, { DEMO_pushMetrics: metrics });
        let permission: NotificationPermission = 'default',
          sub: PushSubscription | null = null;
        let denyNext = false;
        Object.assign(window, {
          DEMO_denyNext: () => {
            denyNext = true;
          },
          DEMO_resetPermission: () => {
            permission = 'default';
          },
        });
        Object.defineProperty(window, 'Notification', {
          configurable: true,
          value: {
            get permission() {
              return permission;
            },
            requestPermission: async () => {
              metrics.permissions++;
              permission = denyNext ? 'denied' : 'granted';
              denyNext = false;
              return permission;
            },
          },
        });
        Object.defineProperty(window, 'PushManager', { configurable: true, value: class {} });
        const manager = {
          getSubscription: async () => sub,
          subscribe: async (options: { applicationServerKey: ArrayBuffer }) => {
            metrics.subscribes++;
            sub = {
              options: { applicationServerKey: options.applicationServerKey },
              toJSON: () => ({
                endpoint: 'https://fcm.googleapis.com/fcm/send/DEMO-browser-device',
                keys: {
                  auth: btoa('x'.repeat(16)).replace(/=/g, ''),
                  p256dh: btoa(String.fromCharCode(4) + 'x'.repeat(64)).replace(/=/g, ''),
                },
              }),
              unsubscribe: async () => {
                metrics.unsubscribes++;
                sub = null;
                return true;
              },
            } as unknown as PushSubscription;
            return sub;
          },
        };
        const registration = { pushManager: manager };
        Object.defineProperty(navigator, 'serviceWorker', {
          configurable: true,
          value: {
            register: async () => registration,
            ready: Promise.resolve(registration),
            getRegistration: async () => registration,
          },
        });
      },
      { client, owner: session.patient_id },
    );
    let subscriptions = 0,
      revocations = 0,
      tests = 0,
      clinicalWrites = 0;
    const workflowBodies: string[] = [];
    page.on('request', (request) => {
      const path = new URL(request.url()).pathname;
      if (path === '/api/reminders/push/subscriptions' && request.method() === 'POST')
        subscriptions++;
      if (
        (path === '/api/reminders/push/unsubscribe' && request.method() === 'POST') ||
        (path.startsWith('/api/reminders/push/subscriptions/') && request.method() === 'DELETE')
      )
        revocations++;
      if (path === '/api/reminders/push/test') tests++;
      if (request.method() !== 'GET' && /^\/api\/(medications|doses|prn|sources)/.test(path))
        clinicalWrites++;
      if (path.includes('/api/agent/workflows')) workflowBodies.push(request.postData() ?? '');
    });
    await page.goto('/');
    const panel = page.getByRole('region', {
      name: say('Current task', '当前办理任务'),
      exact: true,
    });
    async function send(en: string, zh: string) {
      const response = page.waitForResponse(
        (row) => new URL(row.url()).pathname === '/api/agent/workflows/messages',
      );
      await page.locator('.composer-row').getByRole('textbox').fill(say(en, zh));
      await page.locator('.composer-row').getByRole('textbox').press('Enter');
      return (await (await response).json()).workflow;
    }
    const task = await send('enable device notifications', '开启设备通知');
    expect(task.capability_id).toBe('notification.subscribe');
    expect(subscriptions).toBe(0);
    await panel
      .getByRole('button', {
        name: say('Open device notification action', '打开设备通知操作'),
        exact: true,
      })
      .click();
    let dialog = page.getByRole('dialog');
    const enable = dialog.getByRole('button', {
      name: say('Confirm enable on this device', '确认在此设备开启'),
      exact: true,
    });
    await expect(enable).toBeEnabled();
    await dialog.getByRole('button', { name: say('Cancel', '取消'), exact: true }).click();
    expect(
      await page.evaluate(
        () =>
          (window as unknown as { DEMO_pushMetrics: { permissions: number } }).DEMO_pushMetrics
            .permissions,
      ),
    ).toBe(0);
    await page.route(
      '**/api/reminders/push/config?*',
      (route) =>
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ available: false, public_key: null, test_available: false }),
        }),
      { times: 1 },
    );
    await panel
      .getByRole('button', {
        name: say('Open device notification action', '打开设备通知操作'),
        exact: true,
      })
      .click();
    await expect(page.getByRole('dialog')).toContainText(
      say(
        'Background notifications are not configured for this application.',
        '此应用尚未配置后台通知。',
      ),
    );
    await expect(enable).toBeDisabled();
    await page
      .getByRole('dialog')
      .getByRole('button', { name: say('Cancel', '取消'), exact: true })
      .click();
    expect(subscriptions).toBe(0);
    await panel
      .getByRole('button', {
        name: say('Open device notification action', '打开设备通知操作'),
        exact: true,
      })
      .click();
    await expect(
      page.getByRole('dialog').getByRole('button', {
        name: say('Confirm enable on this device', '确认在此设备开启'),
        exact: true,
      }),
    ).toBeEnabled();
    await page.evaluate(() => (window as unknown as { DEMO_denyNext: () => void }).DEMO_denyNext());
    await enable.click();
    await expect(dialog.getByRole('alert')).toBeVisible();
    expect(subscriptions).toBe(0);
    await page.evaluate(() =>
      (window as unknown as { DEMO_resetPermission: () => void }).DEMO_resetPermission(),
    );
    await dialog
      .getByRole('button', { name: say('Refresh device status', '刷新设备状态'), exact: true })
      .click();
    await expect(enable).toBeEnabled();
    await page.route(
      '**/api/reminders/push/subscriptions?*',
      (route) =>
        route.request().method() === 'POST'
          ? route.fulfill({
              status: 503,
              contentType: 'application/json',
              body: JSON.stringify({
                code: 'PROVIDER_UNAVAILABLE',
                message: 'DEMO failed save',
                rule_id: null,
              }),
            })
          : route.continue(),
      { times: 1 },
    );
    await enable.click();
    await expect(dialog.getByRole('alert')).toBeVisible();
    await dialog
      .getByRole('button', { name: say('Refresh device status', '刷新设备状态'), exact: true })
      .click();
    await expect(enable).toBeEnabled();
    await enable.click();
    await expect(dialog).toContainText(
      say(
        'Device subscription saved. Delivery has not been verified.',
        '设备订阅已保存，尚未验证通知送达。',
      ),
    );
    expect(subscriptions).toBe(2);
    await dialog.getByRole('button', { name: say('Cancel', '取消'), exact: true }).click();
    await send('test device notifications', '测试设备通知');
    await page.route(
      '**/api/reminders/push/config?*',
      async (route) => {
        const response = await route.fetch();
        const config = await response.json();
        await route.fulfill({ response, json: { ...config, test_available: false } });
      },
      { times: 1 },
    );
    await panel
      .getByRole('button', {
        name: say('Open device notification action', '打开设备通知操作'),
        exact: true,
      })
      .click();
    await expect(page.getByRole('dialog')).toContainText(
      say('A notification test service is not available.', '通知测试服务不可用。'),
    );
    await expect(
      page.getByRole('dialog').getByRole('button', {
        name: say('Confirm send one test notification', '确认发送一条测试通知'),
        exact: true,
      }),
    ).toBeDisabled();
    expect(tests).toBe(0);
    await page
      .getByRole('dialog')
      .getByRole('button', { name: say('Cancel', '取消'), exact: true })
      .click();
    await panel
      .getByRole('button', {
        name: say('Open device notification action', '打开设备通知操作'),
        exact: true,
      })
      .click();
    dialog = page.getByRole('dialog');
    const testButton = dialog.getByRole('button', {
      name: say('Confirm send one test notification', '确认发送一条测试通知'),
      exact: true,
    });
    await expect(testButton).toBeEnabled();
    expect(tests).toBe(0);
    await testButton.click();
    await expect(dialog).toContainText(
      say(
        'The service accepted the test. Device receipt has not been verified.',
        '服务已接受测试，尚未验证设备实际收到。',
      ),
    );
    await expect(testButton).toBeDisabled();
    await dialog
      .getByRole('button', { name: say('I did not receive it', '我没有收到'), exact: true })
      .click();
    await expect(dialog).toContainText(
      say(
        'Your answer stays on this page and is not a system delivery receipt.',
        '您的回答仅保留在此页面，不是系统送达回执。',
      ),
    );
    await page.screenshot({
      path: `../outputs/assistant-workflows/notification-test-${language}.png`,
      fullPage: true,
    });
    await dialog.getByRole('button', { name: say('Cancel', '取消'), exact: true }).click();
    expect(tests).toBe(1);
    // Add another owned device via the original native fixture API, never via Agent input.
    await call('POST', '/api/reminders/push/subscriptions', {
      endpoint: 'https://fcm.googleapis.com/fcm/send/DEMO-other-device',
      keys: {
        auth: Buffer.from('x'.repeat(16)).toString('base64url'),
        p256dh: Buffer.concat([Buffer.from([4]), Buffer.from('x'.repeat(64))]).toString(
          'base64url',
        ),
      },
    });
    await send('disable device notifications', '关闭设备通知');
    await panel
      .getByRole('button', {
        name: say('Open device notification action', '打开设备通知操作'),
        exact: true,
      })
      .click();
    dialog = page.getByRole('dialog');
    await dialog
      .getByRole('combobox', {
        name: say('Turn off notifications for', '关闭通知的范围'),
        exact: true,
      })
      .selectOption('all');
    await page.screenshot({
      path: `../outputs/assistant-workflows/notification-unsubscribe-${language}.png`,
      fullPage: true,
    });
    expect(revocations).toBe(0);
    await dialog
      .getByRole('button', {
        name: say('Confirm turn off notifications', '确认关闭通知'),
        exact: true,
      })
      .click();
    await expect(dialog).toContainText(
      say('The selected device notifications are off.', '所选设备通知已关闭。'),
    );
    const devices = await call('GET', '/api/reminders/push/subscriptions');
    expect(devices.length).toBe(2);
    expect(devices.every((row: { enabled: boolean }) => !row.enabled)).toBe(true);
    expect(revocations).toBe(2);
    expect(tests).toBe(1);
    expect(clinicalWrites).toBe(0);
    expect((await call('GET', `/api/agent/workflows/tasks/${task.task_id}`)).result_ref).toBeNull();
    expect(workflowBodies.join('')).not.toMatch(
      /p256dh|DEMO-browser-device|DEMO-other-device|subscription_id/,
    );
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
  });
}
