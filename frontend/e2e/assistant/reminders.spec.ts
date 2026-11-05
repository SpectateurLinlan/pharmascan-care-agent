/** Related browser regressions grouped by responsibility; original runtime boundaries stay scoped. */
import { readFileSync } from 'node:fs';
import { test, expect } from '@playwright/test';

// Keep this journey's setup and opt-in gates scoped to its own tests.
test.describe('Reminder queries', () => {
  for (const language of ['en', 'zh'] as const) {
    test(`reads reminders and exports a calendar without sending in ${language}`, async ({
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
      const client = `DEMO-reminder-${crypto.randomUUID()}`,
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
        medication_name: 'DEMO reminder medicine',
        dose_amount: 1,
        dose_unit: 'tablet',
        frequency_kind: 'daily',
        frequency_local_times: ['20:00'],
      });
      await call('POST', `/api/medications/drafts/${med.source_id}/review`, { field_ids: null });
      const challenge = await call(
        'POST',
        `/api/medications/drafts/${med.regimen_id}/challenge?session_id=${session.session_id}`,
        {},
      );
      await call('POST', '/api/medications/activate', {
        regimen_id: med.regimen_id,
        ...Object.fromEntries(
          ['challenge_id', 'session_id', 'session_state', 'session_state_version'].map((key) => [
            key,
            challenge[key],
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
          if ('Notification' in window)
            Notification.requestPermission = () => {
              throw new Error('DEMO test forbids requesting notification permission');
            };
        },
        { client, owner: session.patient_id },
      );
      let calendarReads = 0,
        unsafeWrites = 0,
        planReads = 0;
      const requestBodies: string[] = [];
      page.on('request', (request) => {
        const path = new URL(request.url()).pathname;
        if (path === '/api/reminders/calendar') calendarReads++;
        if (path === '/api/reminders/plan') planReads++;
        if (
          ['POST', 'PATCH', 'PUT', 'DELETE'].includes(request.method()) &&
          (/^\/api\/reminders(?:$|\/push\/(?:test|subscriptions|unsubscribe))/.test(path) ||
            /^\/api\/(medications|doses)\//.test(path))
        )
          unsafeWrites++;
        if (path.includes('/api/agent/workflows/')) requestBodies.push(request.postData() ?? '');
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
      expect((await send('show my reminders', '查看我的提醒')).capability_id).toBe('reminder.list');
      await expect(panel).toContainText('DEMO reminder medicine');
      expect(planReads).toBe(0);
      await panel
        .getByRole('button', { name: say('Next 1 day', '未来 1 天'), exact: true })
        .click();
      const task = await send('export reminder calendar', '导出提醒日历');
      expect(task.capability_id).toBe('reminder.calendar.export');
      await panel
        .getByRole('button', { name: say('Export Calendar', '导出日历'), exact: true })
        .click();
      let dialog = page.getByRole('dialog');
      await dialog
        .getByRole('radio', { name: say('Next 90 days', '未来 90 天'), exact: true })
        .check();
      await dialog.getByRole('button', { name: say('Cancel', '取消'), exact: true }).click();
      expect(calendarReads).toBe(0);
      await panel
        .getByRole('button', { name: say('Export Calendar', '导出日历'), exact: true })
        .click();
      dialog = page.getByRole('dialog');
      await dialog
        .getByRole('radio', { name: say('Next 90 days', '未来 90 天'), exact: true })
        .check();
      await page.route(
        '**/api/reminders/calendar?*',
        (route) =>
          route.fulfill({
            status: 503,
            contentType: 'application/json',
            body: JSON.stringify({
              code: 'PROVIDER_UNAVAILABLE',
              message: 'DEMO calendar unavailable',
              rule_id: null,
            }),
          }),
        { times: 1 },
      );
      await dialog
        .getByRole('button', { name: say('Export .ics', '导出 .ics'), exact: true })
        .click();
      await expect(dialog.getByRole('alert')).toBeVisible();
      await expect(
        dialog.getByRole('radio', { name: say('Next 90 days', '未来 90 天'), exact: true }),
      ).toBeChecked();
      await page.screenshot({
        path: `../outputs/assistant-workflows/reminder-calendar-${language}.png`,
        fullPage: true,
      });
      const downloadEvent = page.waitForEvent('download');
      const calendarResponse = page.waitForResponse(
        (row) => new URL(row.url()).pathname === '/api/reminders/calendar' && row.status() === 200,
      );
      await dialog
        .getByRole('button', { name: say('Export .ics', '导出 .ics'), exact: true })
        .click();
      const response = await calendarResponse;
      expect(response.headers()['content-type']).toContain('text/calendar');
      expect(new URL(response.url()).searchParams.get('range')).toBe('90');
      expect(response.request().headers()['x-assistant-task']).toBe(task.task_id);
      const download = await downloadEvent,
        bytes = readFileSync((await download.path())!).toString('utf8');
      expect(bytes).toContain('BEGIN:VCALENDAR');
      expect(bytes).toContain('DEMO reminder medicine');
      expect(calendarReads).toBe(2);
      expect(
        (await call('GET', `/api/agent/workflows/tasks/${task.task_id}`)).result_ref,
      ).toBeNull();
      expect((await send('check notification status', '查看通知状态')).capability_id).toBe(
        'notification.status',
      );
      await panel
        .getByRole('button', {
          name: say('Check device notification status', '核查设备通知状态'),
          exact: true,
        })
        .click();
      const note = panel.getByText(
        say(
          'Background notifications are not configured for this application.',
          '此应用尚未配置后台通知。',
        ),
        { exact: true },
      );
      await expect(note).toBeVisible();
      await note.scrollIntoViewIfNeeded();
      await page.screenshot({
        path: `../outputs/assistant-workflows/reminder-device-status-${language}.png`,
        fullPage: true,
      });
      expect(unsafeWrites).toBe(0);
      expect(requestBodies.join('')).not.toContain('p256dh');
      expect(requestBodies.join('')).not.toContain('endpoint');
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      );
    });
  }
});

// Keep this journey's setup and opt-in gates scoped to its own tests.
test.describe('Reviewed reminder changes', () => {
  for (const language of ['en', 'zh'] as const) {
    test(`independently confirms reminder changes without duplicate snoozes in ${language}`, async ({
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
      const client = `DEMO-reminder-change-${crypto.randomUUID()}`,
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
        medication_name: 'DEMO reminder change medicine',
        dose_amount: 1,
        dose_unit: 'tablet',
        frequency_kind: 'daily',
        frequency_local_times: ['21:00'],
      });
      await call('POST', `/api/medications/drafts/${med.source_id}/review`, { field_ids: null });
      const challenge = await call(
        'POST',
        `/api/medications/drafts/${med.regimen_id}/challenge?session_id=${session.session_id}`,
        {},
      );
      await call('POST', '/api/medications/activate', {
        regimen_id: med.regimen_id,
        ...Object.fromEntries(
          ['challenge_id', 'session_id', 'session_state', 'session_state_version'].map((key) => [
            key,
            challenge[key],
          ]),
        ),
      });
      // Fixture setup explicitly materializes an existing dose before the observed Assistant journey.
      const plan = await call('GET', '/api/reminders/plan');
      expect(plan.length).toBeGreaterThan(0);
      const beforeRegimens = await call('GET', '/api/me/regimens');
      await page.addInitScript(
        ({ client, owner }) => {
          localStorage.setItem('pharmascan.client_id', client);
          localStorage.setItem(
            `pharmascan.quick-start.v4:${owner}`,
            JSON.stringify({ version: 4, status: 'skipped', step: 0 }),
          );
          if ('Notification' in window)
            Notification.requestPermission = () => {
              throw new Error('DEMO test forbids notification permission');
            };
        },
        { client, owner: session.patient_id },
      );
      let settingsWrites = 0,
        snoozeWrites = 0,
        clinicalWrites = 0;
      const taskBodies: string[] = [];
      page.on('request', (request) => {
        const path = new URL(request.url()).pathname;
        if (request.method() === 'PUT' && path === '/api/me/preferences') settingsWrites++;
        if (request.method() === 'POST' && path === '/api/reminders') snoozeWrites++;
        if (request.method() !== 'GET' && /^\/api\/(medications|doses|prn|sources)/.test(path))
          clinicalWrites++;
        if (path.includes('/api/agent/workflows')) taskBodies.push(request.postData() ?? '');
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
      await send('change reminder settings', '修改提醒设置');
      await panel
        .getByRole('checkbox', { name: say('Medication Reminders', '定时用药提醒'), exact: true })
        .uncheck();
      await panel
        .getByRole('combobox', { name: say('Reminder Lead Time', '用药提醒提前时间'), exact: true })
        .selectOption('30');
      expect(settingsWrites).toBe(0);
      await panel
        .getByRole('button', { name: say('Apply reminder details', '使用提醒资料'), exact: true })
        .click();
      await panel
        .getByRole('button', { name: say('Prepare reminder review', '准备提醒核对'), exact: true })
        .click();
      await panel
        .getByRole('button', { name: say('Review reminder change', '核对提醒变更'), exact: true })
        .click();
      let dialog = page.getByRole('dialog');
      await expect(dialog).toContainText('30');
      await dialog.getByRole('button', { name: say('Cancel', '取消'), exact: true }).click();
      expect(settingsWrites).toBe(0);
      await panel
        .getByRole('button', { name: say('Review reminder change', '核对提醒变更'), exact: true })
        .click();
      await page.route(
        '**/api/me/preferences?*',
        (route) =>
          route.request().method() === 'PUT'
            ? route.fulfill({
                status: 503,
                contentType: 'application/json',
                body: JSON.stringify({
                  code: 'PROVIDER_UNAVAILABLE',
                  message: 'DEMO preference unavailable',
                  rule_id: null,
                }),
              })
            : route.continue(),
        { times: 1 },
      );
      await page
        .getByRole('dialog')
        .getByRole('button', { name: say('Confirm reminder change', '确认提醒变更'), exact: true })
        .click();
      await expect(page.getByRole('dialog').getByRole('alert')).toBeVisible();
      await page
        .getByRole('dialog')
        .getByRole('button', { name: say('Check reminder result', '核查提醒结果'), exact: true })
        .click();
      await panel
        .getByRole('button', { name: say('Edit reminder details', '修改提醒资料'), exact: true })
        .click();
      await panel
        .getByRole('combobox', { name: say('Reminder Lead Time', '用药提醒提前时间'), exact: true })
        .selectOption('60');
      await panel
        .getByRole('button', { name: say('Apply reminder details', '使用提醒资料'), exact: true })
        .click();
      await panel
        .getByRole('button', { name: say('Prepare reminder review', '准备提醒核对'), exact: true })
        .click();
      await panel
        .getByRole('button', { name: say('Review reminder change', '核对提醒变更'), exact: true })
        .click();
      await page.screenshot({
        path: `../outputs/assistant-workflows/reminder-settings-review-${language}.png`,
        fullPage: true,
      });
      await page
        .getByRole('dialog')
        .getByRole('button', { name: say('Confirm reminder change', '确认提醒变更'), exact: true })
        .click();
      await expect(panel).toContainText(
        say(
          'The earlier reminder change was saved. Current settings are shown below.',
          '此前的提醒变更已保存，以下显示当前设置。',
        ),
      );
      const preferences = await call('GET', '/api/me/preferences');
      expect(preferences.reminders_enabled).toBe(false);
      expect(preferences.reminder_lead_minutes).toBe(60);
      expect(settingsWrites).toBe(2);
      await send('snooze a reminder', '稍后提醒我');
      await panel.getByRole('button', { name: /DEMO reminder change medicine/ }).click();
      await panel.getByLabel(say('Minutes later', '延后分钟数'), { exact: true }).fill('30');
      await panel
        .getByRole('button', { name: say('Apply reminder details', '使用提醒资料'), exact: true })
        .click();
      await panel
        .getByRole('button', { name: say('Prepare reminder review', '准备提醒核对'), exact: true })
        .click();
      await panel
        .getByRole('button', { name: say('Review reminder change', '核对提醒变更'), exact: true })
        .click();
      dialog = page.getByRole('dialog');
      await expect(dialog).toContainText('DEMO reminder change medicine');
      expect(snoozeWrites).toBe(0);
      await page.screenshot({
        path: `../outputs/assistant-workflows/reminder-snooze-review-${language}.png`,
        fullPage: true,
      });
      let actualTime = '';
      await page.route(
        '**/api/reminders?*',
        async (route) => {
          if (route.request().method() !== 'POST') return route.continue();
          const response = await route.fetch();
          expect(response.status()).toBe(200);
          actualTime = (await response.json()).remind_at;
          await route.abort('connectionfailed');
        },
        { times: 1 },
      );
      await dialog
        .getByRole('button', { name: say('Confirm reminder change', '确认提醒变更'), exact: true })
        .click();
      await expect(dialog.getByRole('alert')).toBeVisible();
      expect(snoozeWrites).toBe(1);
      await dialog
        .getByRole('button', { name: say('Check reminder result', '核查提醒结果'), exact: true })
        .click();
      await expect(panel).toContainText(say('Current saved snooze', '当前保存的稍后提醒'));
      expect((await call('GET', '/api/reminders'))[0].remind_at).toBe(actualTime);
      expect(snoozeWrites).toBe(1);
      expect(clinicalWrites).toBe(0);
      expect(await call('GET', '/api/me/regimens')).toEqual(beforeRegimens);
      expect(taskBodies.join('')).not.toContain('p256dh');
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      );
    });
  }
});
