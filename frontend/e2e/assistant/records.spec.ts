/** Related browser regressions grouped by responsibility; original runtime boundaries stay scoped. */
import { test, expect } from '@playwright/test';

// Keep this journey's setup and opt-in gates scoped to its own tests.
test.describe('Record queries', () => {
  for (const language of ['en', 'zh'] as const) {
    test(`queries actual patient records, sources and summaries in ${language}`, async ({
      page,
      baseURL,
    }) => {
      expect(new URL(baseURL!).hostname).toBe('127.0.0.1');
      expect((await (await page.request.get('/api/health')).json()).database).toBe(
        'simulated_in_memory',
      );
      if (language === 'en') await page.setViewportSize({ width: 1280, height: 900 });
      const say = (en: string, zh: string) => (language === 'zh' ? zh : en);
      const client = `DEMO-records-${crypto.randomUUID()}`;
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
      const draft = await (
        await page.request.post(`/api/medications/drafts?client_id=${client}`, {
          data: {
            medication_name: 'DEMO recorded PRN',
            dose_amount: 1,
            dose_unit: 'tablet',
            is_prn: true,
            food_instruction: 'DEMO original PRN instructions',
          },
        })
      ).json();
      expect(
        (
          await page.request.post(
            `/api/medications/drafts/${draft.source_id}/review?client_id=${client}`,
            { data: { field_ids: null } },
          )
        ).ok(),
      ).toBe(true);
      const activation = await (
        await page.request.post(
          `/api/medications/drafts/${draft.regimen_id}/challenge?client_id=${client}&session_id=${session.session_id}`,
          { data: {} },
        )
      ).json();
      expect(
        (
          await page.request.post(`/api/medications/activate?client_id=${client}`, {
            data: {
              regimen_id: draft.regimen_id,
              challenge_id: activation.challenge_id,
              session_id: activation.session_id,
              session_state: activation.session_state,
              session_state_version: activation.session_state_version,
            },
          })
        ).ok(),
      ).toBe(true);
      const report = {
        regimen_id: draft.regimen_id,
        intake_status: 'taken',
        idempotency_key: `DEMO-${crypto.randomUUID()}`,
      };
      const confirmation = await (
        await page.request.post(`/api/prn/report/challenge?client_id=${client}`, { data: report })
      ).json();
      expect(
        (
          await page.request.post(`/api/prn/report?client_id=${client}`, {
            data: { ...report, challenge_id: confirmation.challenge_id },
          })
        ).ok(),
      ).toBe(true);
      const original = await page.request.get(
        `/api/me/dose-history?client_id=${client}&regimen_id=${draft.regimen_id}`,
      );
      expect(original.ok(), await original.text()).toBe(true);
      const before = await original.json();
      expect(before.entries).toHaveLength(1);
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
      const panel = page.getByRole('region', {
        name: say('Current task', '当前办理任务'),
        exact: true,
      });
      const writes: string[] = [];
      page.on('request', (request) => {
        if (
          request.method() === 'POST' &&
          /\/api\/(?:prn|doses|medications)\//.test(new URL(request.url()).pathname)
        )
          writes.push(request.url());
      });
      for (const [en, zh, key] of [
        ["show today's medicines", '查看今日用药', 'medication.today'],
        ['show due doses', '查看待自述剂次', 'medication.due'],
        ['show record catalogue', '查看记录目录', 'record.catalogue'],
        ['show medication history', '查看用药历史', 'medication.history'],
        ['check medication status', '查看服药状态', 'medication.status'],
        ['view medication sources', '查看药物原始来源', 'medication.source.view'],
        ['show my medication instructions', '查看我的服药说明', 'medication.instructions'],
        ['show weekly medication summary', '查看本周用药统计', 'record.summary'],
        ['prepare for my visit', '准备复诊', 'record.visit.prepare'],
        ['show medication records', '查看服药记录', 'record.history'],
      ] as const) {
        const sent = page.waitForResponse(
          (response) => new URL(response.url()).pathname === '/api/agent/workflows/messages',
        );
        await composer.fill(say(en, zh));
        await composer.press('Enter');
        const response = await sent;
        expect(response.ok(), await response.text()).toBe(true);
        let view = (await response.json()).workflow;
        expect(view.capability_id).toBe(key);
        if (view.missing_fields.includes('medication_id')) {
          await panel
            .getByRole('button', {
              name: `${say('View record', '查看记录')}: DEMO recorded PRN`,
              exact: true,
            })
            .click();
          await expect(
            panel.getByRole('heading', { name: 'DEMO recorded PRN', level: 3, exact: true }),
          ).toBeVisible();
        }
        await expect(panel).toContainText('DEMO recorded PRN');
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
          true,
        );
        expect(
          await panel
            .getByRole('button', { name: /^Confirm record$|^确认记录$|^Review this medication$/ })
            .count(),
        ).toBe(0);
        if (key === 'medication.source.view')
          await expect(panel).toContainText('DEMO original PRN instructions');
        if (key === 'record.summary') {
          const selection = panel.getByRole('combobox', {
            name: say('Summary period', '统计范围'),
          });
          await selection.selectOption('month');
          await panel
            .getByRole('button', { name: say('Apply record filters', '应用记录筛选'), exact: true })
            .click();
          await expect(selection).toHaveValue('month');
        }
        if (key === 'record.history') {
          const selection = panel.getByRole('combobox', { name: say('History range', '历史范围') });
          await selection.selectOption('7');
          await panel
            .getByRole('button', { name: say('Apply record filters', '应用记录筛选'), exact: true })
            .click();
          await expect(
            panel.getByRole('button', {
              name: say('Apply record filters', '应用记录筛选'),
              exact: true,
            }),
          ).toBeDisabled();
          await expect(panel).toContainText(say('Patient reported taken', '患者自述已服用'));
          await page.screenshot({
            path: `../outputs/assistant-workflows/records-query-${language}.png`,
            fullPage: true,
          });
        }
      }
      expect(writes).toEqual([]);
      expect(
        await (
          await page.request.get(
            `/api/me/dose-history?client_id=${client}&regimen_id=${draft.regimen_id}`,
          )
        ).json(),
      ).toEqual(before);
    });
  }
});

// Keep this journey's setup and opt-in gates scoped to its own tests.
test.describe('Intake reports', () => {
  for (const language of ['en', 'zh'] as const) {
    for (const prn of [false, true]) {
      test(`independently confirms ${prn ? 'PRN' : 'scheduled'} patient report in ${language}`, async ({
        page,
        baseURL,
      }) => {
        expect(new URL(baseURL!).hostname).toBe('127.0.0.1');
        expect((await (await page.request.get('/api/health')).json()).database).toBe(
          'simulated_in_memory',
        );
        if (language === 'en') await page.setViewportSize({ width: 1280, height: 900 });
        const say = (en: string, zh: string) => (language === 'zh' ? zh : en);
        const client = `DEMO-report-${crypto.randomUUID()}`,
          name = `DEMO ${prn ? 'PRN' : 'scheduled'} patient medicine`;
        const session = await (
          await page.request.post('/api/demo/start', { data: { client_id: client } })
        ).json();
        await page.request.put(`/api/me/preferences?client_id=${client}`, {
          data: { preferred_language: language, voice_enabled: false, tts_autoplay: false },
        });
        const draft = await (
          await page.request.post(`/api/medications/drafts?client_id=${client}`, {
            data: {
              medication_name: name,
              dose_amount: 1,
              dose_unit: 'tablet',
              ...(prn
                ? { is_prn: true, food_instruction: 'DEMO original PRN instructions' }
                : { frequency_kind: 'daily', frequency_local_times: ['20:00'] }),
            },
          })
        ).json();
        expect(
          (
            await page.request.post(
              `/api/medications/drafts/${draft.source_id}/review?client_id=${client}`,
              { data: { field_ids: null } },
            )
          ).ok(),
        ).toBe(true);
        const summary = await (
          await page.request.post(
            `/api/medications/drafts/${draft.regimen_id}/challenge?client_id=${client}&session_id=${session.session_id}`,
            { data: {} },
          )
        ).json();
        expect(
          (
            await page.request.post(`/api/medications/activate?client_id=${client}`, {
              data: {
                regimen_id: draft.regimen_id,
                challenge_id: summary.challenge_id,
                session_id: summary.session_id,
                session_state: summary.session_state,
                session_state_version: summary.session_state_version,
              },
            })
          ).ok(),
        ).toBe(true);
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
        let confirmations = 0,
          reports = 0;
        page.on('request', (request) => {
          const path = new URL(request.url()).pathname;
          if (request.method() === 'POST' && /\/api\/(?:prn|doses\/[^/]+)\/report/.test(path)) {
            if (path.endsWith('/challenge')) confirmations++;
            else reports++;
          }
        });
        await page.goto('/');
        const composer = page.locator('.composer-row').getByRole('textbox');
        const sent = page.waitForResponse(
          (response) => new URL(response.url()).pathname === '/api/agent/workflows/messages',
        );
        await composer.fill(
          prn
            ? say('record an as-needed dose', '记录按需服药自述')
            : say('record a dose', '记录服药自述'),
        );
        await composer.press('Enter');
        const response = await sent;
        expect(response.ok(), await response.text()).toBe(true);
        const initial = (await response.json()).workflow;
        const panel = page.getByRole('region', {
          name: say('Current task', '当前办理任务'),
          exact: true,
        });
        await panel
          .getByRole('button', { name: `${say('Choose plan', '选择计划')}: ${name}`, exact: true })
          .click();
        expect(confirmations).toBe(0);
        expect(reports).toBe(0);
        if (language === 'zh' && prn) {
          await panel.getByRole('button', { name: '不保存本次办理', exact: true }).click();
          await expect(
            panel.getByRole('button', { name: '核对服药自述', exact: true }),
          ).toHaveCount(0);
          await panel.getByRole('button', { name: '保存本次任务并继续核对', exact: true }).click();
        }
        await panel
          .getByRole('button', { name: say('Review dose report', '核对服药自述'), exact: true })
          .click();
        const patient = panel.getByRole('region', {
          name: say('Patient dose report', '患者服药自述'),
          exact: true,
        });
        await expect(
          patient.getByRole('button', { name: say('Taken', '已服用'), exact: true }),
        ).toBeEnabled();
        expect(confirmations).toBe(0);
        expect(reports).toBe(0);
        await patient.getByRole('button', { name: say('Taken', '已服用'), exact: true }).click();
        const sheet = page.getByRole('dialog', {
          name: say('Confirm your dose report', '确认服药记录'),
          exact: true,
        });
        await expect(sheet).toContainText(name);
        expect(reports).toBe(0);
        await sheet.getByRole('button', { name: say('Cancel', '取消'), exact: true }).click();
        expect(reports).toBe(0);
        await patient.getByRole('button', { name: say('Taken', '已服用'), exact: true }).click();
        await expect(sheet).toBeVisible();
        await page.screenshot({
          path: `../outputs/assistant-workflows/patient-report-${language}-${prn ? 'prn' : 'scheduled'}.png`,
          fullPage: true,
        });
        let lost = false;
        if (language === 'en' && prn)
          await page.route(
            '**/api/prn/report?*',
            async (route) => {
              lost = true;
              const actual = await route.fetch();
              expect(actual.ok()).toBe(true);
              await route.abort('failed');
            },
            { times: 1 },
          );
        await sheet
          .getByRole('button', { name: say('Confirm record', '确认记录'), exact: true })
          .click();
        if (language === 'en' && prn) {
          await sheet.getByRole('button', { name: 'Check report result', exact: true }).click();
          expect(lost).toBe(true);
        }
        await expect(panel).toContainText(say('Your patient report was saved.', '患者自述已保存'));
        await expect(sheet).toBeHidden();
        expect(reports).toBe(1);
        const state = await (
          await page.request.get(
            `/api/agent/workflows/tasks/${initial.task_id}?client_id=${client}`,
          )
        ).json();
        expect(state.state).toBe('completed');
        expect(state.result_ref.kind).toBe('dose_event');
        expect(state.visible_fields.ingestion_proven).toBe(false);
        const history = await page.request.get(
          `/api/me/dose-history?client_id=${client}&regimen_id=${draft.regimen_id}`,
        );
        expect(history.ok()).toBe(true);
        const records = (await history.json()).entries;
        expect(records.filter((row: { reported: boolean }) => row.reported)).toHaveLength(1);
        expect(records.find((row: { reported: boolean }) => row.reported).intake_status).toBe(
          'reported_taken',
        );
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
          true,
        );
      });
    }
  }
});

// Keep this journey's setup and opt-in gates scoped to its own tests.
test.describe('Historical reports and corrections', () => {
  for (const language of ['en', 'zh'] as const) {
    test(`independent historical report and append-only correction in ${language}`, async ({
      page,
      baseURL,
    }) => {
      expect(new URL(baseURL!).hostname).toBe('127.0.0.1');
      expect((await (await page.request.get('/api/health')).json()).database).toBe(
        'simulated_in_memory',
      );
      if (language === 'en') await page.setViewportSize({ width: 1280, height: 900 });
      const client = 'DEMO-history-' + language,
        say = (en: string, zh: string) => (language === 'zh' ? zh : en);
      const session = await (
        await page.request.post('/api/demo/start', { data: { client_id: client } })
      ).json();
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
      let challenges = 0,
        writes = 0;
      page.on('request', (request) => {
        if (
          request.method() === 'POST' &&
          new URL(request.url()).pathname.includes('/late-report')
        ) {
          if (request.url().includes('/challenge')) challenges++;
          else writes++;
        }
      });
      await page.goto('/');
      const panel = page.getByRole('region', {
        name: say('Current task', '当前办理任务'),
        exact: true,
      });
      const composer = page.locator('.composer-row').getByRole('textbox');
      async function start(correction: boolean) {
        await composer.fill(
          correction
            ? say('correct a dose report', '更正服药记录')
            : say('record a late dose', '补记服药'),
        );
        await composer.press('Enter');
        await panel
          .getByRole('button', {
            name: new RegExp(say('Select occurrence', '选择剂次') + ': DEMO historical medicine'),
          })
          .click();
        await panel
          .getByRole('button', {
            name: say('Prepare historical review', '准备历史核对'),
            exact: true,
          })
          .click();
        await panel
          .getByRole('button', {
            name: say('Review historical report', '核对历史自述'),
            exact: true,
          })
          .click();
      }
      await start(false);
      expect(challenges).toBe(0);
      expect(writes).toBe(0);
      const sheet = page.getByRole('dialog');
      await sheet.getByRole('radio').first().check();
      await sheet.getByRole('combobox').selectOption('forgot_to_record');
      await sheet
        .getByRole('button', { name: say('Review report', '核对自述'), exact: true })
        .click();
      await expect(
        sheet.getByRole('button', { name: say('Confirm report', '确认记录'), exact: true }),
      ).toBeEnabled();
      expect(writes).toBe(0);
      await page.keyboard.press('Escape');
      await expect(sheet).toBeHidden();
      expect(writes).toBe(0);
      await panel
        .getByRole('button', { name: say('Review historical report', '核对历史自述'), exact: true })
        .click();
      await sheet.getByRole('radio').first().check();
      await sheet.getByRole('combobox').selectOption('forgot_to_record');
      await sheet
        .getByRole('textbox', { name: say('Notes (optional)', '备注（可选）'), exact: true })
        .fill('DEMO retained historical entries');
      await sheet
        .getByRole('button', { name: say('Review report', '核对自述'), exact: true })
        .click();
      await expect(
        sheet.getByRole('button', { name: say('Confirm report', '确认记录'), exact: true }),
      ).toBeEnabled();
      await page.screenshot({
        path: `../outputs/assistant-workflows/historical-${language}.png`,
        fullPage: true,
      });
      let lost = false;
      if (language === 'en')
        await page.route(
          '**/api/me/doses/*/late-report?*',
          async (route) => {
            const actual = await route.fetch();
            expect(actual.ok()).toBe(true);
            lost = true;
            await route.abort('failed');
          },
          { times: 1 },
        );
      if (language === 'zh')
        await page.route('**/api/me/doses/*/late-report?*', (route) => route.abort('failed'), {
          times: 1,
        });
      await sheet
        .getByRole('button', { name: say('Confirm report', '确认记录'), exact: true })
        .click();
      if (language === 'en') {
        await sheet.getByRole('button', { name: 'Check report result', exact: true }).click();
        expect(lost).toBe(true);
      }
      if (language === 'zh') {
        await sheet.getByRole('button', { name: '核查自述结果', exact: true }).click();
        await expect(sheet.getByRole('textbox', { name: '备注（可选）', exact: true })).toHaveValue(
          'DEMO retained historical entries',
        );
        await expect(sheet.getByRole('combobox')).toHaveValue('forgot_to_record');
        await expect(sheet.getByRole('button', { name: '确认记录', exact: true })).toHaveCount(0);
        await sheet.getByRole('button', { name: '核对自述', exact: true }).click();
        await sheet.getByRole('button', { name: '确认记录', exact: true }).click();
      }
      await expect(panel).toContainText(
        say('Your historical patient report was saved.', '历史患者自述已保存'),
      );
      await expect(sheet).toBeHidden();
      expect(writes).toBe(language === 'zh' ? 2 : 1);
      await start(true);
      await sheet.getByRole('radio').last().check();
      await sheet.getByRole('combobox').selectOption('correcting_record');
      await sheet
        .getByRole('button', { name: say('Review report', '核对自述'), exact: true })
        .click();
      await sheet
        .getByRole('button', { name: say('Confirm report', '确认记录'), exact: true })
        .click();
      await expect(sheet).toBeHidden();
      await expect(panel).toContainText(
        say('Your historical patient report was saved.', '历史患者自述已保存'),
      );
      expect(writes).toBe(language === 'zh' ? 3 : 2);
      const response = await page.request.get(
        `/api/me/dose-follow-ups?client_id=${client}&include_reported=true`,
      );
      const actual = (await response.json()).items.find(
        (row: { medication_name: string; report_id: string | null }) =>
          row.medication_name === 'DEMO historical medicine' && row.report_id,
      );
      const audit = await (
        await page.request.get(
          `/api/me/doses/${actual.occurrence_id}/late-reports?client_id=${client}`,
        )
      ).json();
      expect(audit.corrections.map((row: { intake_status: string }) => row.intake_status)).toEqual([
        'reported_taken',
        'unsure',
      ]);
      expect(audit.original).toBeNull();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      );
    });
  }
});
