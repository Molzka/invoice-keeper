import { defineConfig } from '@playwright/test';

const baseURL = process.env.E2E_BASE_URL;
if (!baseURL || !process.env.E2E_ADMIN_USERNAME || !process.env.E2E_ADMIN_PASSWORD) {
  throw new Error('Set E2E_BASE_URL, E2E_ADMIN_USERNAME and E2E_ADMIN_PASSWORD for an isolated test stack.');
}
const origin = new URL(baseURL);
if (!['http:', 'https:'].includes(origin.protocol) || origin.username || origin.password
  || origin.pathname !== '/' || origin.search || origin.hash) {
  throw new Error('E2E_BASE_URL must be an HTTP(S) origin without credentials, a path, query or fragment.');
}

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  forbidOnly: true,
  retries: 0,
  timeout: 60_000,
  globalTimeout: 300_000,
  expect: { timeout: 10_000 },
  reporter: [['line'], ['html', { open: 'never' }]],
  use: {
    baseURL: origin.origin,
    browserName: 'chromium',
    locale: 'ru-RU',
    timezoneId: 'Europe/Moscow',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
});
