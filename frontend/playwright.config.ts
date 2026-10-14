import { defineConfig } from '@playwright/test';
export default defineConfig({ testDir:'./e2e', outputDir:'../outputs/playwright-results', timeout:300000, expect:{timeout:30000}, workers:1, retries:0,
  reporter:'line', use:{baseURL:process.env.QA_BASE_URL ?? 'http://127.0.0.1:5174',viewport:{width:390,height:844},
    launchOptions:{executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ?? 'C:/Program Files/Google/Chrome/Application/chrome.exe'},
    trace:'off',screenshot:'off',video:'off'} });
