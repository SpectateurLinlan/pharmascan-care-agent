/** Related browser regressions grouped by responsibility; original runtime boundaries stay scoped. */
import { test, expect } from '@playwright/test';
import type { MedicationSummary } from '../../src/api/client';
import { mockPatientApp } from '../support/patientAppFixture';
import { writeFileSync } from 'node:fs';

// Keep this journey's setup and opt-in gates scoped to its own tests.
test.describe('Form grids', () => {
  test('page grids preserve columns, compact navigation and visible form labels', async ({
    page,
  }) => {
    test.setTimeout(120000);
    const { prefs, errors } = await mockPatientApp(page);
    for (const language of ['en', 'zh'])
      for (const scale of [100, 150]) {
        prefs.preferred_language = language;
        prefs.text_scale_percent = scale;
        await page.goto('/e2e/support/patientApp.html?shell=1');
        for (const width of [390, 430, 768, 1024, 1280, 1600, 1920]) {
          await page.setViewportSize({ width, height: 1000 });
          await page.locator('[data-guide="me"]').click();
          await expect(page.locator('.me-category')).toHaveCount(3);
          await expect(page.locator('.me-category .ui-row__hint')).toHaveCount(0);
          await expect(page.locator('.me-app-info .ui-row')).toHaveCount(3);
          if (language === 'en' && scale === 100 && [390, 1600].includes(width))
            await page.screenshot({ path: `../outputs/polish-a-me-${width}.png` });
          await page.locator('[data-guide="records"]').click();
          const columns = await page
            .locator('.records-navigation-group .ui-rows')
            .evaluate((el) => getComputedStyle(el).gridTemplateColumns.split(' ').length);
          const mainWidth = await page.locator('.app-main').evaluate((el) => el.clientWidth);
          const rem = await page.evaluate(() =>
            parseFloat(getComputedStyle(document.documentElement).fontSize),
          );
          // Records has used the compact 20rem container breakpoint since before this cleanup.
          expect(columns).toBe(mainWidth >= 20 * rem ? 2 : 1);
          await expect(page.locator('.records-summary-actions button')).toHaveCount(3);
          if (language === 'en' && scale === 100 && [390, 1600].includes(width))
            await page.screenshot({ path: `../outputs/polish-a-records-${width}.png` });
          await page.locator('[data-guide="medicines"]').click();
          const shortcuts = page.locator('.medicine-shortcuts');
          const grid = await shortcuts.evaluate(
            (el) => getComputedStyle(el).gridTemplateColumns.split(' ').length,
          );
          await expect(shortcuts.locator('button')).toHaveCount(2);
          const first = await shortcuts.locator('button').first().boundingBox();
          const last = await shortcuts.locator('button').last().boundingBox();
          if (grid === 2) {
            expect(first!.y).toBeCloseTo(last!.y, 0);
            expect(first!.width).toBeCloseTo(last!.width, 0);
          }
          expect(
            await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
          ).toBe(true);
          if (language === 'en' && scale === 100 && [390, 1600].includes(width))
            await page.screenshot({ path: `../outputs/polish-a-${width}.png` });
        }
      }
    expect(errors).toEqual([]);
  });
});

// Keep this journey's setup and opt-in gates scoped to its own tests.
test.describe('Page layout and records', () => {
  test('same-condition visual evidence for four dashboard surfaces', async ({ page }) => {
    const { errors } = await mockPatientApp(page);
    await page.goto('/e2e/support/patientApp.html?shell=1');
    for (const width of [390, 1280, 1920]) {
      await page.setViewportSize({ width, height: 1000 });
      for (const destination of ['today', 'medicines', 'records', 'me']) {
        await page.locator(`[data-guide="${destination}"]`).click();
        await expect(page.locator('.app-main')).toBeVisible();
        await page.screenshot({
          path: `../outputs/polish-a1-${process.env.UX_CAPTURE_PHASE ?? 'after'}-${destination}-${width}.png`,
          fullPage: true,
        });
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
          true,
        );
      }
    }
    expect(errors).toEqual([]);
  });

  test('all root pages share the viewport baseline at enlarged fonts and zoom-equivalent widths', async ({
    page,
  }) => {
    test.setTimeout(120000);
    const mock = await mockPatientApp(page);
    const measurements: object[] = [];
    for (const language of ['en', 'zh'])
      for (const font of [100, 150]) {
        mock.prefs.preferred_language = language;
        mock.prefs.text_scale_percent = font;
        await page.goto('/e2e/support/patientApp.html?shell=1');
        // Effective CSS widths exercise browser-zoom reflow, not native zoom controls.
        for (const width of [
          390,
          430,
          768,
          1024,
          1280,
          1600,
          1920,
          Math.round(1280 / 1.25),
          Math.round(1280 / 1.5),
        ]) {
          await page.setViewportSize({ width, height: 1000 });
          for (const destination of ['today', 'medicines', 'records', 'me']) {
            await page.locator(`[data-guide="${destination}"]`).click();
            const metric = await page.evaluate(() => {
              const main = document.querySelector('.app-main')!,
                header = document.querySelector('.app-header')!;
              const m = main.getBoundingClientRect(),
                h = header.getBoundingClientRect(),
                style = getComputedStyle(header);
              return {
                width: innerWidth,
                contentWidth: m.width,
                mainLeft: m.left,
                headerStart: h.left + parseFloat(style.paddingLeft),
                canvas: getComputedStyle(document.body).backgroundColor,
              };
            });
            expect(Math.abs(metric.mainLeft - metric.headerStart)).toBeLessThan(2);
            expect(metric.contentWidth).toBeLessThanOrEqual(1201);
            expect(
              await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
            ).toBe(true);
            measurements.push({ language, font, destination, ...metric });
            if (language === 'zh' && font === 150 && [390, 1280].includes(width))
              await page.screenshot({
                path: `../outputs/polish-a1-zh150-${destination}-${width}.png`,
                fullPage: true,
              });
          }
        }
      }
    writeFileSync(
      '../outputs/polish-a1-layout-measurements.json',
      JSON.stringify(measurements, null, 2),
    );
    expect(mock.errors).toEqual([]);
  });

  const medicine = (i: number): MedicationSummary => ({
    medication_id: `DEMO-med-${i}`,
    regimen_id: `DEMO-plan-${i}`,
    display_name: `DEMO synthetic long medicine name ${i} / ${'extended name '.repeat(2)}`,
    dose_amount: 1,
    dose_unit: 'tablet',
    is_prn: false,
    version_no: 1,
    identity_status: 'user_reviewed_document',
    source_backed: true,
    frequency_rule: { kind: 'daily', local_times: ['08:00'], days_of_week: [] },
  });

  test('responsive data volumes, languages, enlarged text and readable navigation', async ({
    page,
  }) => {
    test.setTimeout(120000);
    const mock = await mockPatientApp(page);
    for (const language of ['en', 'zh'])
      for (const font of [100, 150]) {
        mock.prefs.preferred_language = language;
        mock.prefs.text_scale_percent = font;
        for (const count of [0, 1, 2, 5, 10]) {
          mock.setMedications(Array.from({ length: count }, (_, i) => medicine(i)));
          await page.goto('/e2e/support/patientApp.html?shell=1');
          for (const width of [390, 430, 768, 1024, 1280, 1600, 1920]) {
            await page.setViewportSize({ width, height: 1000 });
            await page.locator('[data-guide="medicines"]').click();
            await expect(page.locator('.medicine-shortcuts button')).toHaveCount(2);
            await expect(page.locator('.medicine-shortcuts')).toBeVisible();
            // Medication rows retain every real fetched item, including long names.
            await expect(
              page.locator('.current-medications-card .medication-list-row'),
            ).toHaveCount(count);
            expect(
              await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
            ).toBe(true);
            if (count === 2 && language === 'zh' && font === 100 && width === 1280)
              await page.screenshot({
                path: '../outputs/my-medicines-active-1280.png',
                fullPage: true,
              });
            if ([0, 1, 5, 10].includes(count) && [390, 1280, 1920].includes(width)) {
              await page.locator('[data-guide="today"]').click();
              if (count > 1) await expect(page.locator('.medicine-list-row')).toHaveCount(count);
              const overflow = await page.evaluate(() =>
                [...document.querySelectorAll('main *')]
                  .filter((el) => el.getBoundingClientRect().right > innerWidth + 1)
                  .map((el) => ({
                    tag: el.tagName,
                    class: el.className,
                    right: el.getBoundingClientRect().right,
                  }))
                  .slice(0, 12),
              );
              expect(
                await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
                JSON.stringify({ width, font, language, count, overflow }),
              ).toBe(true);
              if (count === 10 && font === 150 && language === 'zh' && width === 1280)
                await page.screenshot({
                  path: '../outputs/polish-a1-today-ten-zh150-1280.png',
                  fullPage: true,
                });
            }
          }
        }
      }
    expect(mock.errors).toEqual([]);
  });
});

// Keep this journey's setup and opt-in gates scoped to its own tests.
test.describe('Account layout', () => {
  test('Me cards fit mobile, tablet and desktop layouts', async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    const mock = await mockPatientApp(page, false, {
      token: 'DEMO.me-layout-token',
      owner: 'd00d0000-0000-4000-8000-000000000001',
    });
    mock.setSourceTasks([]);
    mock.prefs.display_name = 'DEMO Guest';
    await page.goto('/e2e/support/patientApp.html?shell=1');
    await page.locator('[data-guide="me"]').click();
    await expect(page.locator('.me-category')).toHaveCount(3);
    await expect(page.locator('.me-app-info .ui-row')).toHaveCount(3);
    for (const width of [390, 768, 1280]) {
      await page.setViewportSize({ width, height: 900 });
      await expect
        .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
        .toBe(true);
      const cards = await page.locator('.me-category').evaluateAll((rows) =>
        rows.map((row) => {
          const box = row.getBoundingClientRect();
          return { x: box.x, y: box.y, width: box.width, height: box.height };
        }),
      );
      expect(cards.every((card) => card.width > 0 && card.height > 0)).toBe(true);
      // The shell caps content below the 58rem three-column breakpoint; these widths use two columns.
      expect(Math.round(cards[0]!.y)).toBe(Math.round(cards[1]!.y));
      expect(cards[2]!.y).toBeGreaterThan(cards[0]!.y);
      expect(cards[2]!.width).toBeGreaterThan(cards[0]!.width);
      expect(Math.abs(cards[0]!.height - cards[1]!.height)).toBeLessThan(2);
      expect(cards.every((card) => card.x >= 0 && card.x + card.width <= width)).toBe(true);
      await page.screenshot({ path: `../outputs/me-responsive-${width}.png`, fullPage: true });
    }
    expect(errors).toEqual([]);
  });
});
