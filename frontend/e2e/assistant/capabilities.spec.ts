/** Actual loopback app/API with synthetic owners; capability results are read back. */
import { test, expect } from '@playwright/test';

// T8 additions run with --grep P06-T8; accepted T1 journeys below are not replayed.
for (const language of ['en', 'zh'] as const) {
  test(`[P06-T8] exact care confirmation and independent draft recovery in ${language}`, async ({
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
    const client = `DEMO-P06-T8-${crypto.randomUUID()}`,
      say = (en: string, zh: string) => (language === 'zh' ? zh : en);
    async function call(
      method: string,
      path: string,
      data?: unknown,
      headers?: Record<string, string>,
    ) {
      const response = await page.request.fetch(
        `${path}${path.includes('?') ? '&' : '?'}client_id=${client}`,
        { method, ...(data ? { data } : {}), ...(headers ? { headers } : {}) },
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
      medication_name: 'DEMO T8 medicine',
      dose_amount: 1,
      dose_unit: 'tablet',
      is_prn: true,
      food_instruction: 'DEMO reviewed as-needed source',
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
    const catalog = await call('GET', '/api/agent/workflows/capabilities');
    expect(catalog.capabilities).toHaveLength(91);
    expect(
      catalog.capabilities.filter(
        (row: { reason: string | null }) => row.reason === 'not_implemented',
      ),
    ).toEqual([]);
    expect(
      catalog.capabilities.find((row: { id: string }) => row.id === 'notification.test'),
    ).toMatchObject({ available: false, reason: 'notification_send_not_authorized' });
    const unrelated = await call('POST', '/api/agent/workflows/tasks', {
      capability_id: 'medication.enroll',
      workspace_id: crypto.randomUUID(),
      client_event_id: crypto.randomUUID(),
      values: { method: 'manual', medication_name: 'DEMO retained independent draft' },
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
    await page.goto('/#assistant');
    const panel = () =>
        page.getByRole('region', { name: say('Current task', '当前办理任务'), exact: true }),
      composer = () => page.locator('.composer-row').getByRole('textbox');
    async function draft(en: string, zh: string, values: Record<string, unknown>) {
      const response = page.waitForResponse(
        (row) => new URL(row.url()).pathname === '/api/agent/workflows/messages',
      );
      await composer().fill(say(en, zh));
      await composer().press('Enter');
      const received = await response;
      expect(received.ok(), await received.text()).toBe(true);
      const task = (await received.json()).workflow;
      const filled = await call('POST', `/api/agent/workflows/tasks/${task.task_id}/events`, {
        event_id: crypto.randomUUID(),
        expected_revision: task.revision,
        kind: 'provide_fields',
        values,
      });
      const ready = await call('POST', `/api/agent/workflows/tasks/${task.task_id}/events`, {
        event_id: crypto.randomUUID(),
        expected_revision: filled.revision,
        kind: 'prepare_confirmation',
        values: {},
      });
      await panel()
        .getByRole('button', { name: say('Check task status', '核查办理状态'), exact: true })
        .click();
      await expect(
        panel().getByRole('button', {
          name: say('Review care record', '核对关怀记录'),
          exact: true,
        }),
      ).toBeVisible();
      return ready;
    }
    let writes = 0;
    page.on('request', (request) => {
      if (
        request.method() === 'POST' &&
        new URL(request.url()).pathname.startsWith('/api/me/care-tasks')
      )
        writes++;
    });
    await draft('add a medication followup', '添加用药跟进', {
      title: 'DEMO proposed linked followup',
      category: 'monitoring',
      due_at: '2099-10-28T12:00:00Z',
      regimen_id: med.regimen_id,
      reminder_minutes: null,
    });
    await panel()
      .getByRole('button', { name: say('Review care record', '核对关怀记录'), exact: true })
      .click();
    await expect(page.getByRole('dialog')).toContainText('DEMO proposed linked followup');
    await expect(page.getByRole('dialog')).toContainText('DEMO T8 medicine · v1');
    expect(writes).toBe(0);
    await page
      .getByRole('dialog')
      .getByRole('button', { name: say('Cancel', '取消'), exact: true })
      .click();
    expect(writes).toBe(0);
    await panel()
      .getByRole('button', { name: say('Review care record', '核对关怀记录'), exact: true })
      .click();
    await page.screenshot({
      path: `../outputs/assistant-workflows/T8-linked-${language}.png`,
      fullPage: true,
    });
    await page
      .getByRole('dialog')
      .getByRole('button', { name: say('Confirm record', '确认记录'), exact: true })
      .click();
    await expect(page.getByRole('dialog')).toHaveCount(0);
    expect(writes).toBe(1);
    const saved = (await call('GET', '/api/me/care-tasks'))[0];
    expect(saved).toMatchObject({
      title: 'DEMO proposed linked followup',
      category: 'monitoring',
      medication_id: null,
      regimen_id: med.regimen_id,
    });
    await draft('edit a medication followup', '编辑用药跟进', {
      task_id: saved.id,
      expected_version: saved.version,
      title: 'DEMO NEW reviewed followup',
      category: 'symptom_follow_up',
      clear_plan: true,
    });
    await panel()
      .getByRole('button', { name: say('Review care record', '核对关怀记录'), exact: true })
      .click();
    await expect(page.getByRole('dialog')).toContainText('DEMO NEW reviewed followup');
    await expect(page.getByRole('dialog')).toContainText(
      say('Remove the medication and plan link', '移除药物和计划关联'),
    );
    expect(writes).toBe(1);
    await page.screenshot({
      path: `../outputs/assistant-workflows/T8-unlinked-${language}.png`,
      fullPage: true,
    });
    await page
      .getByRole('dialog')
      .getByRole('button', { name: say('Confirm record', '确认记录'), exact: true })
      .click();
    await expect(page.getByRole('dialog')).toHaveCount(0);
    expect(writes).toBe(2);
    expect((await call('GET', '/api/me/care-tasks'))[0]).toMatchObject({
      title: 'DEMO NEW reviewed followup',
      category: 'symptom_follow_up',
      medication_id: null,
      regimen_id: null,
    });
    const observation = await call('POST', '/api/agent/workflows/tasks', {
      capability_id: 'observation.add',
      workspace_id: crypto.randomUUID(),
      client_event_id: crypto.randomUUID(),
      values: { description: 'DEMO original observation', occurred_at: '2026-10-27T12:00:00Z' },
    });
    const reviewed = await call(
      'POST',
      `/api/agent/workflows/tasks/${observation.task_id}/events`,
      {
        event_id: crypto.randomUUID(),
        expected_revision: observation.revision,
        kind: 'prepare_confirmation',
        values: {},
      },
    );
    const original = await call(
      'PUT',
      '/api/me/health-observations',
      { ...reviewed.visible_fields.care_review.payload, confirmed: true },
      { 'X-Assistant-Task': reviewed.task_id, 'X-Assistant-Revision': String(reviewed.revision) },
    );
    await call('POST', `/api/agent/workflows/tasks/${observation.task_id}/events`, {
      event_id: crypto.randomUUID(),
      expected_revision: reviewed.revision,
      kind: 'report_business_result',
      values: {},
    });
    await call('PUT', '/api/me/health-observations', {
      ...reviewed.visible_fields.care_review.payload,
      description: 'DEMO later correction',
      confirmed: true,
    });
    expect(
      (await call('GET', `/api/agent/workflows/tasks/${observation.task_id}`)).visible_fields
        .historical_result,
    ).toBe(true);
    expect(original.description).toBe('DEMO original observation');
    const pdfResponse = await page.request.post(
      `/api/evidence/gallery/${med.medication_id}/pdfs?client_id=${client}&filename=DEMO_T8.pdf&category=other`,
      {
        data: Buffer.from('%PDF-1.7\n1 0 obj<</Type/Catalog>>endobj\n%%EOF'),
        headers: { 'Content-Type': 'application/pdf' },
      },
    );
    expect(pdfResponse.ok(), await pdfResponse.text()).toBe(true);
    const pdf = (await pdfResponse.json()).file;
    const selected = await call('POST', '/api/agent/workflows/tasks', {
      capability_id: 'library.pdf.edit',
      workspace_id: crypto.randomUUID(),
      client_event_id: crypto.randomUUID(),
      values: {
        medication_id: med.medication_id,
        file_id: pdf.id,
        expected_version: 1,
        title: 'DEMO proposed PDF',
        category: 'other',
        description: '',
      },
    });
    await call('PATCH', `/api/evidence/library-files/${pdf.id}`, {
      expected_version: 1,
      title: 'DEMO changed elsewhere',
      category: 'other',
      description: '',
    });
    const stale = await call('GET', `/api/agent/workflows/tasks/${selected.task_id}`);
    expect(stale).toMatchObject({
      state: 'failed_recoverable',
      input_fields: { expected_version: 1, title: 'DEMO proposed PDF' },
    });
    expect(stale.actions[0].options[0].value).toBe(`${pdf.id}:2`);
    const list = await call('GET', '/api/agent/workflows/tasks');
    expect(list.some((row: { task_id: string }) => row.task_id === unrelated.task_id)).toBe(true);
    await page
      .getByRole('button', { name: /Continue assistant tasks|继续助手任务/, exact: true })
      .click();
    await expect(
      page.getByRole('button', { name: /DEMO retained independent draft/ }),
    ).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
  });
}

for (const language of ['en', 'zh'] as const) {
  for (const kind of ['legacy', 'missing', 'bound'] as const)
    test(`recovers a ${kind} unfinished draft in ${language}`, async ({ page, baseURL }) => {
      expect(new URL(baseURL!).hostname).toBe('127.0.0.1');
      expect((await (await page.request.get('/api/health')).json()).database).toBe(
        'simulated_in_memory',
      );
      const client = `DEMO-recovery-${kind}-${language}-${crypto.randomUUID()}`;
      const session = await (
        await page.request.post('/api/demo/start', { data: { client_id: client } })
      ).json();
      await page.request.put(`/api/me/preferences?client_id=${client}`, {
        data: { preferred_language: language, voice_enabled: false, tts_autoplay: false },
      });
      const name = 'DEMO browser recovered plan';
      let originalTask: string | null = null;
      if (kind === 'bound') {
        const started = await (
          await page.request.post(`/api/agent/workflows/tasks?client_id=${client}`, {
            data: {
              capability_id: 'medication.enroll',
              workspace_id: crypto.randomUUID(),
              client_event_id: crypto.randomUUID(),
              values: {
                method: 'manual',
                medication_name: name,
                dose_amount: 1,
                dose_unit: 'tablet',
                frequency_rule: { kind: 'daily', local_times: ['20:00'] },
              },
            },
          })
        ).json();
        originalTask = started.task_id;
        expect(
          (
            await page.request.post(
              `/api/agent/workflows/tasks/${started.task_id}/events?client_id=${client}`,
              {
                data: {
                  event_id: crypto.randomUUID(),
                  expected_revision: started.revision,
                  kind: 'prepare_confirmation',
                  values: {},
                },
              },
            )
          ).ok(),
        ).toBe(true);
      } else
        expect(
          (
            await page.request.post(`/api/medications/drafts?client_id=${client}`, {
              data: {
                medication_name: name,
                ...(kind === 'legacy' ? { dose_amount: 1 } : {}),
                dose_unit: 'tablet',
                frequency_kind: 'daily',
                frequency_local_times: ['20:00'],
              },
            })
          ).ok(),
        ).toBe(true);
      const before = await (await page.request.get(`/api/me/regimens?client_id=${client}`)).json();
      expect(before).toHaveLength(1);
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
      await composer.fill(language === 'zh' ? '继续药物草稿' : 'resume a medication draft');
      await composer.press('Enter');
      const panel = page.getByRole('region', {
        name: language === 'zh' ? '当前办理任务' : 'Current task',
      });
      await panel
        .getByRole('button', {
          name: `${language === 'zh' ? '选择草稿' : 'Choose draft'}: ${name} · v1`,
          exact: true,
        })
        .click();
      if (kind === 'bound') {
        await panel
          .getByRole('button', {
            name: language === 'zh' ? '继续原登记任务' : 'Continue original enrollment',
            exact: true,
          })
          .click();
      } else {
        if (kind === 'missing') {
          await expect(
            panel.getByRole('spinbutton', {
              name: language === 'zh' ? '每次用量' : 'Amount per dose',
            }),
          ).toBeVisible();
          const submission = page.waitForResponse(
            (response) => new URL(response.url()).pathname === '/api/agent/workflows/messages',
          );
          await composer.fill('2');
          await composer.press('Enter');
          const response = await submission;
          expect(response.ok(), await response.text()).toBe(true);
        }
        await panel
          .getByRole('button', {
            name: language === 'zh' ? '核对这项药物' : 'Review this medication',
            exact: true,
          })
          .click();
      }
      const current = await (await page.request.get(`/api/me/regimens?client_id=${client}`)).json();
      expect(current).toHaveLength(kind === 'missing' ? 2 : 1);
      expect(current.every((row: { state: string }) => row.state !== 'active')).toBe(true);
      if (originalTask) {
        const original = await (
          await page.request.get(`/api/agent/workflows/tasks/${originalTask}?client_id=${client}`)
        ).json();
        expect(original.state).toBe('awaiting_confirmation');
      }
      await panel
        .getByRole('checkbox', {
          name:
            language === 'zh'
              ? '我已对照原始服用说明核对过以上内容。'
              : 'I have checked these details against my original instructions.',
        })
        .check();
      if (kind === 'missing') {
        await panel
          .getByRole('checkbox', {
            name:
              language === 'zh'
                ? '我已对照来源核对原记录中的药物名称。'
                : 'I checked the original medication name against its source.',
          })
          .check();
        await page.screenshot({
          path: `../outputs/assistant-workflows/original-name-review-${language}.png`,
          fullPage: true,
        });
      }
      await panel
        .getByRole('button', {
          name: language === 'zh' ? '添加此药物' : 'Add this medication',
          exact: true,
        })
        .click();
      const activating = page.waitForResponse(
        (response) => new URL(response.url()).pathname === '/api/medications/activate',
      );
      await page
        .getByRole('button', {
          name: language === 'zh' ? '确认：激活此用药计划' : 'Yes, save this medication',
          exact: true,
        })
        .click();
      const activation = await activating;
      expect(activation.ok(), await activation.text()).toBe(true);
      await expect(panel).toContainText(
        language === 'zh' ? '药物计划已启用。' : 'The medication plan is active.',
      );
      const after = await (await page.request.get(`/api/me/regimens?client_id=${client}`)).json();
      expect(after.filter((row: { state: string }) => row.state === 'active')).toHaveLength(1);
      expect(after.find((row: { state: string }) => row.state === 'active').dose_amount).toBe(
        kind === 'missing' ? 2 : 1,
      );
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      );
      await page.screenshot({
        path: `../outputs/assistant-workflows/draft-recovered-${language}-${kind}.png`,
        fullPage: true,
      });
    });
  for (const loseResponse of [false, true]) {
    test(`deletes a reviewed draft${loseResponse ? ' with lost-response recovery' : ''} in ${language}`, async ({
      page,
      baseURL,
    }) => {
      expect(new URL(baseURL!).hostname).toBe('127.0.0.1');
      expect((await (await page.request.get('/api/health')).json()).database).toBe(
        'simulated_in_memory',
      );
      if ((language === 'en' && !loseResponse) || (language === 'zh' && loseResponse))
        await page.setViewportSize({ width: 1280, height: 900 });
      const client = `DEMO-delete-${language}-${crypto.randomUUID()}`;
      const session = await (
        await page.request.post('/api/demo/start', { data: { client_id: client } })
      ).json();
      await page.request.put(`/api/me/preferences?client_id=${client}`, {
        data: { preferred_language: language, voice_enabled: false, tts_autoplay: false },
      });
      const draft = await (
        await page.request.post(`/api/medications/drafts?client_id=${client}`, {
          data: {
            medication_name: 'DEMO browser deletable',
            dose_amount: 1,
            dose_unit: 'tablet',
            frequency_kind: 'daily',
            frequency_local_times: ['08:00'],
          },
        })
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
      await page.goto('/');
      let writes = 0;
      page.on('request', (request) => {
        if (
          request.method() === 'DELETE' &&
          new URL(request.url()).pathname.endsWith(draft.regimen_id)
        )
          writes++;
      });
      if (loseResponse)
        await page.route(
          '**/api/medications/unfinished/draft/*',
          async (route) => {
            const actual = await route.fetch();
            expect(actual.ok()).toBe(true);
            await route.abort('failed');
          },
          { times: 1 },
        );
      const composer = page.locator('.composer-row').getByRole('textbox');
      await composer.fill(language === 'zh' ? '删除药物草稿' : 'delete a medication draft');
      await composer.press('Enter');
      const panel = page.getByRole('region', {
        name: language === 'zh' ? '当前办理任务' : 'Current task',
      });
      await panel
        .getByRole('button', {
          name: `${language === 'zh' ? '选择草稿' : 'Choose draft'}: DEMO browser deletable · v1`,
          exact: true,
        })
        .click();
      await panel
        .getByRole('button', {
          name: language === 'zh' ? '核对删除这份草稿' : 'Review deleting this draft',
          exact: true,
        })
        .click();
      await panel
        .getByRole('button', { name: language === 'zh' ? '删除草稿' : 'Delete draft', exact: true })
        .click();
      const dialog = page.getByRole('dialog', {
        name: language === 'zh' ? '删除这份草稿？' : 'Delete this draft?',
      });
      await expect(dialog).toContainText(
        language === 'zh' ? '将移除 1 个未确认计划版本' : '1 unfinished plan version',
      );
      expect(writes).toBe(0);
      expect(
        await (await page.request.get(`/api/me/regimens?client_id=${client}`)).json(),
      ).toHaveLength(1);
      await page.screenshot({
        path: `../outputs/assistant-workflows/delete-review-${language}-${loseResponse ? 'loss' : 'normal'}.png`,
        fullPage: true,
      });
      await dialog
        .getByRole('button', {
          name: language === 'zh' ? '确认删除' : 'Confirm delete',
          exact: true,
        })
        .click();
      if (loseResponse) {
        await dialog
          .getByRole('button', {
            name: language === 'zh' ? '核查删除结果' : 'Check deletion result',
            exact: true,
          })
          .click();
      }
      await expect(panel).toContainText(
        language === 'zh'
          ? '草稿已删除，已确认的历史记录已保留。'
          : 'The draft was deleted. Confirmed history is retained.',
      );
      await expect(dialog).toBeHidden();
      expect(writes).toBe(1);
      expect(await (await page.request.get(`/api/me/regimens?client_id=${client}`)).json()).toEqual(
        [],
      );
      const receipt = await page.request.get(
        `/api/medications/unfinished/draft/${draft.regimen_id}/receipt?client_id=${client}`,
      );
      expect(receipt.headers()['cache-control']).toBe('no-store');
      expect(await receipt.json()).toEqual({
        deleted: true,
        medication_deleted: true,
        cleanup_pending: false,
      });
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      );
    });
  }
  test(`reads saved plans and unfinished setup inside chat in ${language}`, async ({
    page,
    baseURL,
  }) => {
    expect(new URL(baseURL!).hostname).toBe('127.0.0.1');
    expect((await (await page.request.get('/api/health')).json()).database).toBe(
      'simulated_in_memory',
    );
    const client = `DEMO-capabilities-${language}-${crypto.randomUUID()}`;
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
    const created = await page.request.post(`/api/medications/drafts?client_id=${client}`, {
      data: {
        medication_name: 'DEMO browser saved plan',
        dose_amount: 1,
        dose_unit: 'tablet',
        frequency_kind: 'daily',
        frequency_local_times: ['20:00'],
      },
    });
    expect(created.ok()).toBe(true);
    const before = await (await page.request.get(`/api/me/regimens?client_id=${client}`)).json();
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
    await composer.fill(language === 'zh' ? '查看用药计划' : 'show medication plans');
    await composer.press('Enter');
    const panel = page.getByRole('region', {
      name: language === 'zh' ? '当前办理任务' : 'Current task',
    });
    await panel
      .getByRole('button', {
        name: `${language === 'zh' ? '查看记录' : 'View record'}: DEMO browser saved plan`,
        exact: true,
      })
      .click();
    await expect(panel.getByRole('heading', { name: 'DEMO browser saved plan' })).toBeVisible();
    await expect(
      panel.getByText(language === 'zh' ? '草稿' : 'Draft', { exact: true }),
    ).toBeVisible();
    await expect(panel).toContainText('20:00');
    await composer.fill(language === 'zh' ? '查看未完成登记' : 'show unfinished medication setup');
    await composer.press('Enter');
    await expect(
      panel.getByRole('heading', {
        name: language === 'zh' ? '未完成的药物登记' : 'Unfinished medication setup',
      }),
    ).toBeVisible();
    await expect(panel.getByRole('heading', { name: 'DEMO browser saved plan' })).toBeVisible();
    await panel
      .getByRole('button', {
        name: language === 'zh' ? '不保存本次办理' : 'Do not save this workflow',
        exact: true,
      })
      .click();
    await expect(
      panel.getByRole('button', {
        name: language === 'zh' ? '保存本次查询' : 'Save this query',
        exact: true,
      }),
    ).toBeVisible();
    await panel
      .getByRole('button', {
        name: language === 'zh' ? '核查办理状态' : 'Check task status',
        exact: true,
      })
      .click();
    await expect(panel.getByRole('heading', { name: 'DEMO browser saved plan' })).toBeVisible();
    expect(await (await page.request.get(`/api/me/regimens?client_id=${client}`)).json()).toEqual(
      before,
    );
    expect(await page.evaluate(() => JSON.stringify({ ...localStorage }))).not.toContain(
      'DEMO browser saved plan',
    );
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    await page.screenshot({
      path: `../outputs/assistant-workflows/medication-reads-${language}.png`,
      fullPage: true,
    });
  });
  test(`stops only the reviewed recorded plan after independent confirmation in ${language}`, async ({
    page,
    baseURL,
  }) => {
    expect(new URL(baseURL!).hostname).toBe('127.0.0.1');
    expect((await (await page.request.get('/api/health')).json()).database).toBe(
      'simulated_in_memory',
    );
    const client = `DEMO-stop-${language}-${crypto.randomUUID()}`;
    const session = await (
      await page.request.post('/api/demo/start', { data: { client_id: client } })
    ).json();
    await page.request.put(`/api/me/preferences?client_id=${client}`, {
      data: { preferred_language: language, voice_enabled: false, tts_autoplay: false },
    });
    const draft = await (
      await page.request.post(`/api/medications/drafts?client_id=${client}`, {
        data: {
          medication_name: 'DEMO browser stop plan',
          dose_amount: 1,
          dose_unit: 'tablet',
          frequency_kind: 'daily',
          frequency_local_times: ['20:00'],
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
    const challenge = await (
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
            challenge_id: challenge.challenge_id,
            session_id: challenge.session_id,
            session_state: challenge.session_state,
            session_state_version: challenge.session_state_version,
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
    await page.goto('/');
    let stops = 0;
    page.on('request', (request) => {
      if (request.method() === 'POST' && new URL(request.url()).pathname.endsWith('/end')) stops++;
    });
    const composer = page.locator('.composer-row').getByRole('textbox');
    await composer.fill(language === 'zh' ? '停止追踪用药计划' : 'stop tracking medication');
    await composer.press('Enter');
    const panel = page.getByRole('region', {
      name: language === 'zh' ? '当前办理任务' : 'Current task',
    });
    await panel
      .getByRole('button', {
        name: `${language === 'zh' ? '选择计划' : 'Choose plan'}: DEMO browser stop plan · v1`,
        exact: true,
      })
      .click();
    await panel
      .getByRole('button', {
        name: language === 'zh' ? '核对停止追踪此计划' : 'Review stopping this plan',
        exact: true,
      })
      .click();
    await panel
      .getByRole('button', {
        name: language === 'zh' ? '停止追踪此疗程' : 'Stop tracking this regimen',
        exact: true,
      })
      .click();
    expect(stops).toBe(0);
    const before = await (await page.request.get(`/api/me/regimens?client_id=${client}`)).json();
    expect(before[0].state).toBe('active');
    const confirmation = page.getByRole('dialog', {
      name: language === 'zh' ? '停止此记录中的计划？' : 'Stop this recorded plan?',
    });
    await confirmation
      .getByRole('button', { name: language === 'zh' ? '确认停止' : 'Confirm stop', exact: true })
      .click();
    await expect(panel).toContainText(
      language === 'zh'
        ? '这项记录中的计划已结束，历史记录已保留。'
        : 'This recorded plan has ended. Past records are retained.',
    );
    expect(stops).toBe(1);
    const after = await (await page.request.get(`/api/me/regimens?client_id=${client}`)).json();
    expect(after).toHaveLength(1);
    expect(after[0]).toMatchObject({
      regimen_id: draft.regimen_id,
      state: 'ended',
      dose_amount: 1,
      dose_unit: 'tablet',
      version_no: 1,
    });
    expect(after[0].frequency_rule).toEqual(before[0].frequency_rule);
    await page.screenshot({
      path: `../outputs/assistant-workflows/plan-ended-${language}.png`,
      fullPage: true,
    });
  });
}
