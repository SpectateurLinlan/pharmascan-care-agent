import { expect, test, type Page } from '@playwright/test';
import { mkdirSync, writeFileSync } from 'node:fs';
import path from 'node:path';

async function closeHeldPage(page: Page, release: () => void) {
  // Keep the request guards installed until no app code can issue another fetch.
  try {
    await page.close({ runBeforeUnload: false });
  } finally {
    release();
  }
}

for (const { language, width } of [
  { language: 'en', width: 390 },
  { language: 'zh', width: 1280 },
]) {
  test(`composer stays editable and consistent across loading stages in ${language}`, async ({
    page,
    baseURL,
  }) => {
    expect(new URL(baseURL!).hostname).toBe('127.0.0.1');
    await page.setViewportSize({ width, height: 844 });
    const owner = 'DEMO-composer-owner';
    await page.addInitScript((owner) => {
      localStorage.setItem(
        `pharmascan.quick-start.v5:${owner}`,
        JSON.stringify({ version: 5, status: 'skipped', step: 0 }),
      );
      localStorage.setItem(`pharmascan.conversation:${owner}`, 'DEMO-owned-conversation');
    }, owner);
    let releaseApp!: () => void,
      releaseHealth!: () => void,
      releaseResume!: () => void,
      releaseUsage!: () => void;
    const app = new Promise<void>((resolve) => {
      releaseApp = resolve;
    });
    const health = new Promise<void>((resolve) => {
      releaseHealth = resolve;
    });
    const resume = new Promise<void>((resolve) => {
      releaseResume = resolve;
    });
    const usage = new Promise<void>((resolve) => {
      releaseUsage = resolve;
    });
    let appRequested = false;
    const calls: string[] = [];
    const pageErrors: string[] = [];
    page.on('pageerror', (error) => pageErrors.push(error.name));
    await page.route('**/*', async (route) => {
      const url = new URL(route.request().url());
      if (url.origin !== new URL(baseURL!).origin) return route.abort();
      if (!url.pathname.startsWith('/api/')) {
        if (/\/assets\/mountApplication-.*\.js$/.test(url.pathname)) {
          appRequested = true;
          await app;
        }
        try {
          return await route.continue();
        } catch (error) {
          if (!page.isClosed()) throw error;
          return;
        }
      }
      calls.push(`${route.request().method()} ${url.pathname}`);
      let body: unknown = [];
      if (url.pathname === '/api/health') {
        await health;
        body = {
          status: 'ok',
          database: 'simulated_in_memory',
          runtime_contract: 'patient-ux-reminders-v1',
        };
      } else if (url.pathname === '/api/me/preferences')
        body = {
          patient_id: owner,
          preferred_language: language,
          timezone: 'Asia/Singapore',
          voice_enabled: true,
          text_size: 'standard',
        };
      else if (url.pathname === '/api/demo/start')
        body = {
          patient_id: owner,
          session_id: 'DEMO-session',
          demo_only: true,
          seeded_medication_count: 0,
          note: 'DEMO_ONLY',
        };
      else if (url.pathname === '/api/me/medications')
        body = { medications: [], item_count: 0, note: 'DEMO_ONLY' };
      else if (url.pathname === '/api/agent/workflows/capabilities')
        body = { contract_version: 1, enabled: false, capabilities: [] };
      else if (url.pathname === '/api/agent/usage') {
        await usage;
        body = { llm_user_turns: 1, limit: 20, next_reset_at: '2026-11-07T00:00:00+08:00' };
      } else if (url.pathname.endsWith('/DEMO-owned-conversation/resume')) {
        await resume;
        body = { session_id: 'DEMO-restored' };
      } else if (url.pathname.endsWith('/DEMO-owned-conversation'))
        body = {
          conversation: {
            id: 'DEMO-owned-conversation',
            title: 'DEMO',
            created_at: '2026-11-06T00:00:00Z',
            updated_at: '2026-11-06T00:00:00Z',
          },
          entries: [],
          next_before: null,
        };
      try {
        await route.fulfill({ json: body });
      } catch (error) {
        if (!page.isClosed()) throw error;
      }
    });
    const output = path.resolve('../internal/acceptance/composer-browser');
    mkdirSync(output, { recursive: true });
    try {
      await page.goto('/', { waitUntil: 'commit' });
      await expect.poll(() => appRequested).toBe(true);
      const input = page.locator('.composer-row').getByRole('textbox');
      await input.fill('DEMO early draft');
      // The capsule owns focus; the inner field cannot draw a square over its corners.
      expect(await input.evaluate((el) => getComputedStyle(el).outlineStyle)).toBe('none');
      await page.screenshot({ path: path.join(output, `${language}-html.png`), fullPage: true });
      releaseApp();
      await expect(page.locator('#startup-shell')).toHaveCount(0);
      await expect.poll(() => calls.includes('GET /api/me/preferences')).toBe(true);
      const send = page.locator('.composer-send');
      await expect(send).toHaveText(language === 'zh' ? '发送' : 'Send');
      expect((await page.locator('.composer-row').boundingBox())!.height).toBeLessThanOrEqual(44);
      expect(
        await send.evaluate((el) => Number.parseFloat(getComputedStyle(el).borderTopLeftRadius)),
      ).toBeLessThan(20);
      await input.fill('DEMO pending connection');
      const pendingColor = await send.evaluate((el) => getComputedStyle(el).backgroundColor);
      expect(await input.evaluate((el) => getComputedStyle(el).outlineStyle)).toBe('none');
      await page.screenshot({ path: path.join(output, `${language}-pending.png`), fullPage: true });
      releaseHealth();
      await expect
        .poll(() => calls.includes('POST /api/agent/conversations/DEMO-owned-conversation/resume'))
        .toBe(true);
      await expect(input).toBeEnabled();
      await input.fill('DEMO editable during restore');
      await input.press('Enter');
      await expect(send).toBeDisabled();
      expect(calls.some((call) => call === 'POST /api/agent/message')).toBe(false);
      expect(await send.evaluate((el) => getComputedStyle(el).backgroundColor)).toBe(pendingColor);
      expect(
        await page
          .locator('.composer-row')
          .evaluate((el) => getComputedStyle(el).gridTemplateColumns.split(' ').length),
      ).toBe(4);
      expect(await send.evaluate((el) => getComputedStyle(el).whiteSpace)).toBe('nowrap');
      releaseUsage();
      await expect(page.locator('.composer-allowance')).toBeVisible();
      expect(
        await page
          .locator('.composer-row')
          .evaluate((el) => getComputedStyle(el).gridTemplateColumns.split(' ').length),
      ).toBe(5);
      releaseResume();
      await expect(send).toBeEnabled();
      expect((await page.locator('.composer-row').boundingBox())!.height).toBeLessThanOrEqual(44);
      await expect(input).toHaveValue('DEMO editable during restore');
      await expect(input).toBeFocused();
      await expect(send).toHaveText(language === 'zh' ? '发送' : 'Send');
      await page.screenshot({ path: path.join(output, `${language}-ready.png`), fullPage: true });
      await page.evaluate(() => {
        document.documentElement.setAttribute('data-text-scale', '150');
        document.documentElement.style.setProperty('--font-scale', '1.5');
      });
      expect(
        await page
          .locator('.composer-row')
          .evaluate((el) => getComputedStyle(el).gridTemplateColumns.split(' ').length),
      ).toBe(4);
      expect(await send.evaluate((el) => getComputedStyle(el).whiteSpace)).toBe('nowrap');
      await expect(input).toBeEnabled();
      if (width === 390) {
        await page.setViewportSize({ width: 318, height: 844 });
        await page.getByRole('button', { name: 'Open full chat' }).click();
        const workspaceRow = page.locator('.conversation-workspace .composer-row');
        await expect(workspaceRow).toBeVisible();
        const row = await workspaceRow.boundingBox();
        const button = await workspaceRow.locator('.composer-send').boundingBox();
        expect(button!.x + button!.width).toBeLessThanOrEqual(row!.x + row!.width);
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      );
      expect(pageErrors).toEqual([]);
    } finally {
      await closeHeldPage(page, () => {
        releaseApp();
        releaseHealth();
        releaseResume();
        releaseUsage();
      });
    }
  });
}

for (const width of [390, 1280]) {
  test(`HTML and local input survive held scripts and IME handover at ${width}px`, async ({
    page,
    baseURL,
  }) => {
    expect(new URL(baseURL!).hostname).toBe('127.0.0.1');
    await page.setViewportSize({ width, height: 844 });
    let releaseEntry!: () => void;
    let releaseApp!: () => void;
    const entry = new Promise<void>((resolve) => {
      releaseEntry = resolve;
    });
    const app = new Promise<void>((resolve) => {
      releaseApp = resolve;
    });
    let appRequested = false;
    const apiCalls: string[] = [];
    await page.route('**/*', async (route) => {
      const url = new URL(route.request().url());
      if (url.origin !== new URL(baseURL!).origin) return route.abort();
      if (url.pathname.startsWith('/api/')) {
        apiCalls.push(`${route.request().method()} ${url.pathname}`);
        return route.abort();
      }
      if (/\/assets\/index-.*\.js$|\/src\/main\.tsx$/.test(url.pathname)) await entry;
      if (
        /\/assets\/mountApplication-.*\.js$|\/src\/app\/mountApplication\.tsx$/.test(url.pathname)
      ) {
        appRequested = true;
        await app;
      }
      try {
        await route.continue();
      } catch (error) {
        if (!page.isClosed()) throw error;
      }
    });
    try {
      const started = Date.now();
      await page.goto('/', { waitUntil: 'commit' });
      const early = page.locator('#startup-message');
      await expect(early).toBeVisible();
      const firstInputMs = Date.now() - started;
      expect(
        await page.locator('#startup-shell').evaluate((el) => getComputedStyle(el).fontFamily),
      ).toContain('Segoe');
      await early.fill('DEMO before entry downloaded');
      await early.press('Enter');
      expect(apiCalls).toEqual([]);
      // Composition can start while even the tiny entry is still downloading.
      await early.dispatchEvent('compositionstart');
      releaseEntry();
      await expect.poll(() => appRequested).toBe(true);
      await expect(early).toHaveValue('DEMO before entry downloaded');
      expect(apiCalls).toEqual([]);
      await early.fill('布洛芬 DEMO local draft');
      await early.evaluate((input: HTMLInputElement) => input.setSelectionRange(1, 4));
      if (width === 1280)
        await page.locator('#startup-shell h1').evaluate((el) => {
          el.setAttribute('tabindex', '-1');
          (el as HTMLElement).focus();
        });
      const output = path.resolve('../internal/acceptance/progressive-browser');
      mkdirSync(output, { recursive: true });
      const card = await page.locator('.startup-assistant').boundingBox();
      const composer = await early.boundingBox();
      expect(composer!.y + composer!.height).toBeLessThanOrEqual(card!.y + card!.height);
      await page.screenshot({ path: path.join(output, `shell-${width}.png`), fullPage: true });
      await page.evaluate(() => (document.documentElement.style.fontSize = '150%'));
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      );
      await page.evaluate(() => document.documentElement.style.removeProperty('font-size'));
      releaseApp();
      await expect
        .poll(() =>
          page.evaluate(() => performance.getEntriesByName('medithread:runtime-ready').length),
        )
        .toBe(1);
      await expect(early).toBeVisible();
      await early.dispatchEvent('compositionend');
      await expect(page.locator('#startup-shell')).toHaveCount(0);
      const connected = page.locator('.composer-row').getByRole('textbox');
      await expect(connected).toHaveValue('布洛芬 DEMO local draft');
      if (width === 390) {
        await expect(connected).toBeFocused();
        expect(
          await connected.evaluate((input: HTMLInputElement) => [
            input.selectionStart,
            input.selectionEnd,
          ]),
        ).toEqual([1, 4]);
      } else await expect(connected).not.toBeFocused();
      expect(apiCalls.some((call) => call.startsWith('POST '))).toBe(false);
      await expect(page.locator('.composer-send')).toBeDisabled();
      await page.screenshot({ path: path.join(output, `handover-${width}.png`), fullPage: true });
      writeFileSync(
        path.join(output, `${width}.json`),
        JSON.stringify({
          mode: 'production_static_scripts_held',
          firstInputMs,
          apiCallsBeforeRuntime: 0,
        }),
      );
    } finally {
      await closeHeldPage(page, () => {
        releaseEntry();
        releaseApp();
      });
    }
  });
}

for (const kind of ['js', 'css']) {
  test(`a failed application ${kind} download can retry with its local draft intact`, async ({
    page,
    baseURL,
  }) => {
    expect(new URL(baseURL!).hostname).toBe('127.0.0.1');
    let failDownload = true;
    const html = await (await page.request.get('/')).text();
    test.skip(
      !html.includes('/assets/index-'),
      'Asset retry checks require a production Vite preview.',
    );
    await page.route('**/*', async (route) => {
      const url = new URL(route.request().url());
      if (url.origin !== new URL(baseURL!).origin || url.pathname.startsWith('/api/'))
        return route.abort();
      if (
        (new RegExp(`/assets/mountApplication-.*\\.${kind}$`).test(url.pathname) ||
          (kind === 'js' && url.pathname === '/src/app/mountApplication.tsx')) &&
        failDownload
      )
        return route.abort();
      return route.continue();
    });
    try {
      await page.goto('/', { waitUntil: 'commit' });
      await expect(page.locator('#startup-retry')).toBeVisible();
      await page.locator('#startup-message').fill('DEMO kept after asset failure');
      failDownload = false;
      await page.locator('#startup-retry').click();
      await expect(page.locator('#startup-shell')).toHaveCount(0, { timeout: 5000 });
      await expect(page.locator('.composer-row').getByRole('textbox')).toHaveValue(
        'DEMO kept after asset failure',
      );
      await expect
        .poll(
          () =>
            page.evaluate(() =>
              Array.from(document.styleSheets).some((sheet) => {
                if (!sheet.href?.includes('/mountApplication-')) return false;
                try {
                  return sheet.cssRules.length > 0;
                } catch {
                  return false;
                }
              }),
            ),
          { timeout: 5000 },
        )
        .toBe(true);
    } finally {
      await closeHeldPage(page, () => undefined);
    }
  });
}

test('held startup responses are released only after page disposal', async ({
  page,
  context,
  baseURL,
}) => {
  expect(new URL(baseURL!).hostname).toBe('127.0.0.1');
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  const escaped: string[] = [];
  let held = false;
  // Even the deliberately broken cleanup must never reach the local API proxy.
  await context.route('**/api/**', async (route) => {
    escaped.push(new URL(route.request().url()).pathname);
    await route.abort();
  });
  await page.route('**/*', async (route) => {
    if (new URL(route.request().url()).pathname === '/api/held') {
      held = true;
      await gate;
      try {
        await route.fulfill({ json: {} });
      } catch (error) {
        if (!page.isClosed()) throw error;
      }
      return;
    }
    await route.fulfill({
      contentType: 'text/html',
      body: '<script>fetch("/api/held").then(() => fetch("/api/escaped"))</script>',
    });
  });
  await page.goto('/');
  await expect.poll(() => held).toBe(true);
  let closedWhenReleased = false;
  await closeHeldPage(page, () => {
    closedWhenReleased = page.isClosed();
    release();
  });
  expect(closedWhenReleased).toBe(true);
  expect(page.isClosed()).toBe(true);
  expect(escaped).toEqual([]);
});

// Browser-only startup contract. Every API response is a synthetic fixture;
// use a loopback Vite server with empty Supabase Auth environment variables.
for (const language of ['en', 'zh'] as const) {
  test(`startup composer is immediate and preserves its draft in ${language}`, async ({
    page,
    baseURL,
  }) => {
    expect(new URL(baseURL!).hostname).toBe('127.0.0.1');
    const owner = 'DEMO-startup-browser';
    await page.addInitScript((owner) => {
      localStorage.setItem(
        `pharmascan.quick-start.v5:${owner}`,
        JSON.stringify({ version: 5, status: 'skipped', step: 0 }),
      );
    }, owner);
    let releaseHealth!: () => void;
    let releaseSession!: () => void;
    let releaseRecords!: () => void;
    let releaseSection!: () => void;
    const section = new Promise<void>((resolve) => {
      releaseSection = resolve;
    });
    const requestedSections = new Set<string>();
    const health = new Promise<void>((resolve) => {
      releaseHealth = resolve;
    });
    const session = new Promise<void>((resolve) => {
      releaseSession = resolve;
    });
    const records = new Promise<void>((resolve) => {
      releaseRecords = resolve;
    });
    const calls: string[] = [];
    await page.route('**/*', async (route) => {
      const url = new URL(route.request().url());
      if (url.origin !== new URL(baseURL!).origin) return route.abort();
      if (!url.pathname.startsWith('/api/')) {
        // Cover both the Vite development module and emitted production chunk.
        for (const name of ['MedicinesHub', 'RegimenHistoryScreen']) {
          if (url.pathname.includes(`/${name}.`) || url.pathname.includes(`/${name}-`)) {
            requestedSections.add(name);
            if (name === 'MedicinesHub') await section;
          }
        }
        try {
          return await route.continue();
        } catch (error) {
          if (!page.isClosed()) throw error;
          return;
        }
      }
      calls.push(`${route.request().method()} ${url.pathname}`);
      let body: unknown = [];
      if (url.pathname === '/api/health') {
        await health;
        body = {
          status: 'ok',
          database: 'simulated_in_memory',
          runtime_contract: 'patient-ux-reminders-v1',
        };
      } else if (url.pathname === '/api/me/preferences') {
        body = {
          patient_id: owner,
          preferred_language: language,
          timezone: 'Asia/Singapore',
          voice_enabled: false,
          text_size: 'standard',
        };
      } else if (url.pathname === '/api/demo/start') {
        await session;
        body = {
          patient_id: owner,
          session_id: 'DEMO-startup-session',
          demo_only: true,
          seeded_medication_count: 0,
          note: 'DEMO_ONLY',
        };
      } else if (url.pathname === '/api/me/medications') {
        await records;
        body = { medications: [], item_count: 0, note: 'DEMO_ONLY' };
      } else if (url.pathname === '/api/agent/workflows/capabilities') {
        body = { contract_version: 1, enabled: false, capabilities: [] };
      } else if (url.pathname === '/api/agent/usage') {
        body = { llm_user_turns: 0, limit: 20, next_reset_at: '2026-11-07T00:00:00+08:00' };
      }
      try {
        await route.fulfill({ json: body });
      } catch (error) {
        if (!page.isClosed()) throw error;
      }
    });
    try {
      const started = Date.now();
      await page.goto('/');
      const composer = page.locator('.composer-row').getByRole('textbox');
      await expect(composer).toBeVisible({ timeout: 5000 });
      // These cases cover backend/session readiness after the separate HTML/JS
      // handover cases above; measure the React composer, not a replacing DOM node.
      await expect(page.locator('#startup-shell')).toHaveCount(0);
      const startupSize = await composer.boundingBox();
      const startupSend = await page.locator('.composer-send').boundingBox();
      expect(startupSize!.width).toBeGreaterThan(180);
      expect(startupSize!.width).toBeGreaterThan(startupSend!.width);
      await page.evaluate(() => document.documentElement.setAttribute('data-text-scale', '150'));
      expect((await composer.boundingBox())!.width).toBeGreaterThan(180);
      await page.evaluate(() => document.documentElement.setAttribute('data-text-scale', '100'));
      const firstInputMs = Date.now() - started;
      await composer.fill('DEMO question typed before the backend wakes');
      await composer.press('Enter');
      await composer.press('ArrowLeft');
      await composer.press('Shift+ArrowLeft');
      const selection = await composer.evaluate((input: HTMLInputElement) => [
        input.selectionStart,
        input.selectionEnd,
      ]);
      await expect
        .poll(() => calls.filter((call) => call === 'GET /api/me/preferences').length)
        .toBe(1);
      expect(calls.some((call) => call.startsWith('POST '))).toBe(false);
      await expect(page.locator('.composer-send')).toBeDisabled();
      releaseHealth();
      await expect
        .poll(() => calls.filter((call) => call === 'POST /api/demo/start').length)
        .toBe(1);
      await expect(composer).toHaveValue('DEMO question typed before the backend wakes');
      await expect(page.locator('.composer-send')).toBeDisabled();
      releaseSession();
      await expect(page.locator('.composer-send')).toBeEnabled();
      await expect(composer).toBeFocused();
      expect(
        await composer.evaluate((input: HTMLInputElement) => [
          input.selectionStart,
          input.selectionEnd,
        ]),
      ).toEqual(selection);
      await expect(composer).toHaveValue('DEMO question typed before the backend wakes');
      expect(calls.filter((call) => call.startsWith('POST '))).toEqual(['POST /api/demo/start']);
      await expect(page.getByText('No medication plans have been added.')).not.toBeVisible();
      await expect(page.getByText('尚未添加用药计划。')).not.toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      );
      const output = path.resolve('../internal/acceptance/startup-browser');
      mkdirSync(output, { recursive: true });
      await page.screenshot({ path: path.join(output, `${language}.png`), fullPage: true });
      writeFileSync(
        path.join(output, `${language}.json`),
        JSON.stringify({
          mode: 'intercepted_loopback_demo',
          firstInputMs,
          delayedHealth: true,
          delayedSession: true,
          delayedRecords: true,
          externalCalls: 0,
        }),
      );
      expect(requestedSections.has('MedicinesHub')).toBe(false);
      releaseRecords();
      await page.locator('.patient-nav button').nth(1).click();
      await expect.poll(() => requestedSections.has('MedicinesHub')).toBe(true);
      // Unopened history stays absent even after records become available.
      expect(requestedSections.has('RegimenHistoryScreen')).toBe(false);
      await expect(page.locator('.patient-nav')).toBeVisible();
      await expect(page.locator('.current-medications-card')).not.toBeVisible();
      releaseSection();
      await expect(page.locator('.current-medications-card')).toBeVisible();
      await page.locator('.patient-nav button').first().click();
      await expect(composer).toHaveValue('DEMO question typed before the backend wakes');
    } catch (error) {
      console.log('DEMO startup request paths', calls);
      throw error;
    } finally {
      await closeHeldPage(page, () => {
        releaseHealth();
        releaseSession();
        releaseRecords();
        releaseSection();
      });
    }
  });
}

// Real local FastAPI + in-memory synthetic fixture, never hosted patient data.
// Start create_review_test_app as documented in frontend/README.md; use a Vite
// server with empty Supabase Auth variables and that API as VITE_API_TARGET.
test('language renders before a slow preference response without business refetches', async ({
  page,
  baseURL,
}) => {
  test.skip(
    process.env.RUN_PERFORMANCE_LOCAL !== '1',
    'Explicit local synthetic performance run only',
  );
  expect(baseURL).toMatch(/^http:\/\/(127\.0\.0\.1|localhost):/);
  const health = await (await page.request.get('/api/health')).json();
  expect(health.database).toBe('simulated_in_memory');
  const session = await (
    await page.request.post('/api/demo/start', { data: { client_id: 'DEMO-release-D' } })
  ).json();
  await page.addInitScript((owner) => {
    localStorage.setItem('pharmascan.client_id', 'DEMO-release-D');
    localStorage.setItem(
      `pharmascan.quick-start.v5:${owner}`,
      JSON.stringify({ version: 5, status: 'skipped', step: 0 }),
    );
  }, session.patient_id);
  let releaseSchedule!: () => void;
  const scheduleGate = new Promise<void>((resolve) => {
    releaseSchedule = resolve;
  });
  await page.route('**/api/me/today-attention*', async (route) => {
    const response = await route.fetch();
    await scheduleGate;
    await route.fulfill({ response });
  });
  try {
    await page.goto('/');
    await expect(page.locator('.today-unrecorded__count')).toBeVisible();
    await expect(page.getByText('Loading your reviewed schedule…')).toBeVisible();
  } finally {
    releaseSchedule();
  }
  await expect(page.locator('.medicine-current')).toBeVisible();
  await expect(page.locator('.care-summary__counts')).toBeVisible();
  const draft = page.locator('[data-guide="assistant-composer"] input:not([type="file"])').first();
  await draft.fill('DEMO unsent draft');
  await page.waitForTimeout(300);
  const business: string[] = [];
  page.on('request', (request) => {
    if (
      /\/api\/(reminders\/alerts|doses\/due|me\/(dose-follow-ups|today-attention|care-tasks\/refresh))/.test(
        request.url(),
      )
    )
      business.push(new URL(request.url()).pathname);
  });
  let savesFinished = 0;
  await page.route('**/api/me/preferences*', async (route) => {
    if (route.request().method() !== 'PUT') {
      await route.continue();
      return;
    }
    const response = await route.fetch();
    await new Promise((resolve) => setTimeout(resolve, 800));
    await route.fulfill({ response });
    savesFinished++;
  });
  for (let index = 0; index < 2; index++) {
    const before = await page.locator('.greeting').textContent();
    await page.locator('.language-shortcut').click();
    await expect(page.locator('.greeting')).not.toHaveText(before ?? '');
    expect(savesFinished).toBe(index);
    await expect(draft).toHaveValue('DEMO unsent draft');
    await expect(page.locator('.language-shortcut')).toBeEnabled();
  }
  expect(business).toEqual([]);
});

test('assistant startup samples separate cached and fresh browser contexts', async ({
  browser,
  request,
  baseURL,
}) => {
  test.skip(
    process.env.RUN_ASSISTANT_STARTUP !== '1',
    'Explicit local synthetic startup measurement only',
  );
  test.setTimeout(180000);
  expect(new URL(baseURL!).origin).toBe('http://127.0.0.1:5173');
  const health = await (await request.get('/api/health')).json();
  expect(health.database).toBe('simulated_in_memory');
  const session = await (
    await request.post('/api/demo/start', { data: { client_id: 'DEMO-startup' } })
  ).json();
  const active = await (await request.get('/api/me/medications?client_id=DEMO-startup')).json();
  expect(active.medications).toHaveLength(3);
  await request.put('/api/me/preferences?client_id=DEMO-startup', {
    data: {
      voice_enabled: false,
      tts_autoplay: false,
      reminders_enabled: false,
      preferred_language: 'en',
    },
  });
  const samples: Array<{
    cache: string;
    viewport: string;
    backend: string;
    cpu: string;
    shell_ms: number | null;
    essential_ms: number | null;
    onboarding_blocked: boolean;
  }> = [];
  for (const viewport of [
    { width: 390, height: 844 },
    { width: 1280, height: 900 },
  ]) {
    for (const cache of ['normal-cache', 'cold-browser'] as const) {
      let shared: Awaited<ReturnType<typeof browser.newContext>> | null = null;
      async function context() {
        const value = await browser.newContext({ viewport });
        await value.addInitScript(
          ({ cache, owner }) => {
            localStorage.setItem('pharmascan.client_id', 'DEMO-startup');
            localStorage.setItem(
              `pharmascan.quick-start.v5:${owner}`,
              JSON.stringify({ version: 5, status: 'skipped', step: 0 }),
            );
            sessionStorage.setItem('medithread.performance.v2.enabled', cache);
          },
          { cache, owner: session.patient_id },
        );
        return value;
      }
      if (cache === 'normal-cache') {
        shared = await context();
        const warmup = await shared.newPage();
        await warmup.goto('/');
        await warmup.waitForFunction(
          () => document.querySelector('[data-today-dose-state="ready"]'),
          undefined,
          { timeout: 15000 },
        );
        await warmup.close();
      }
      for (let index = 0; index < 5; index++) {
        const current = shared ?? (await context());
        const page = await current.newPage();
        const cdp = await current.newCDPSession(page);
        await cdp.send('Emulation.setCPUThrottlingRate', { rate: 1 });
        await page.goto('/');
        await page
          .waitForFunction(
            () => {
              const summary = window.medithreadWorkflows?.summary() as
                { captures: Array<{ checkpoints: Array<{ kind: string }> }> } | undefined;
              return summary?.captures
                .at(-1)
                ?.checkpoints.some((row) => row.kind === 'today_essential_ready');
            },
            undefined,
            { timeout: 15000 },
          )
          .catch(() => undefined);
        const timing = await page.evaluate(() => {
          const summary = window.medithreadWorkflows?.summary() as
            { captures: Array<{ checkpoints: Array<{ kind: string; at: number }> }> } | undefined;
          const checkpoints = summary?.captures.at(-1)?.checkpoints ?? [];
          return {
            shell_ms: checkpoints.find((row) => row.kind === 'app_shell_visible')?.at ?? null,
            essential_ms:
              checkpoints.find((row) => row.kind === 'today_essential_ready')?.at ?? null,
            onboarding_blocked: Boolean(document.querySelector('[aria-modal="true"]')),
          };
        });
        samples.push({
          cache,
          viewport: `${viewport.width}x${viewport.height}`,
          backend: 'running_memory_process',
          cpu: 'CDP_rate_1',
          ...timing,
        });
        await page.close();
        if (!shared) await current.close();
      }
      await shared?.close();
    }
  }
  const output = path.resolve('../outputs/assistant-startup');
  mkdirSync(output, { recursive: true });
  writeFileSync(path.join(output, 'samples.json'), JSON.stringify(samples, null, 2));
  expect(samples).toHaveLength(20);
  expect(
    samples.every(
      (row) => row.shell_ms !== null && row.essential_ms !== null && !row.onboarding_blocked,
    ),
  ).toBe(true);
});

test('assistant startup shell remains visible with delayed health and onboarding blocks readiness', async ({
  page,
  request,
  baseURL,
}) => {
  test.skip(
    process.env.RUN_ASSISTANT_STARTUP !== '1',
    'Explicit local synthetic startup measurement only',
  );
  expect(new URL(baseURL!).origin).toBe('http://127.0.0.1:5173');
  const session = await (
    await request.post('/api/demo/start', { data: { client_id: 'DEMO-startup' } })
  ).json();
  await page.addInitScript((owner) => {
    localStorage.setItem('pharmascan.client_id', 'DEMO-startup');
    sessionStorage.setItem('medithread.performance.v2.enabled', 'cold-browser');
    localStorage.removeItem(`pharmascan.quick-start.v5:${owner}`);
  }, session.patient_id);
  let release!: () => void;
  const pending = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route('**/api/health', async (route) => {
    const response = await route.fetch();
    await pending;
    await route.fulfill({ response });
  });
  let releaseSession!: () => void;
  const pendingSession = new Promise<void>((resolve) => {
    releaseSession = resolve;
  });
  await page.route('**/api/demo/start', async (route) => {
    const response = await route.fetch();
    await pendingSession;
    await route.fulfill({ response });
  });
  try {
    try {
      await page.goto('/');
      await expect(
        page.getByRole('heading', { name: 'Welcome to MediThread', exact: true }),
      ).toBeVisible();
      await expect(page.getByRole('navigation', { name: 'Main navigation' })).toBeVisible();
      await expect(page.locator('[data-today-dose-state="ready"]')).toHaveCount(0);
    } finally {
      release();
    }
    await expect(page.locator('[aria-modal="true"]').first()).toBeVisible();
    await page.waitForFunction(() => window.medithreadWorkflows?.enabled);
    const summary = (await page.evaluate(() => window.medithreadWorkflows!.summary())) as {
      captures: Array<{ checkpoints: Array<{ kind: string }> }>;
    };
    expect(
      summary.captures.at(-1)!.checkpoints.some((row) => row.kind === 'app_shell_visible'),
    ).toBe(true);
    expect(
      summary.captures.at(-1)!.checkpoints.some((row) => row.kind === 'today_essential_ready'),
    ).toBe(false);
  } finally {
    releaseSession();
  }
});
