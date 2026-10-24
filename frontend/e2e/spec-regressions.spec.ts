import { randomUUID } from 'node:crypto';
import { expect, test } from '@playwright/test';
import type { Page, TestInfo } from '@playwright/test';
import type { AuthResponse, PaymentOccurrence, PaymentSummary } from '../src/types/api';

const adminUsername = process.env.E2E_ADMIN_USERNAME;
const adminPassword = process.env.E2E_ADMIN_PASSWORD;
if (!adminUsername || !adminPassword) {
  throw new Error('Set E2E_ADMIN_USERNAME and E2E_ADMIN_PASSWORD for the disposable test database.');
}
// The browser zone deliberately differs from the usual server zones (Moscow/Tokyo).
test.use({ timezoneId: 'Pacific/Honolulu', reducedMotion: 'reduce' });

async function responseAfter(page: Page, method: string, path: string, status: number, action: () => Promise<unknown>) {
  const [response] = await Promise.all([
    page.waitForResponse(value => value.request().method() === method && new URL(value.url()).pathname === `/api/v1${path}`),
    action(),
  ]);
  expect(response.status(), `${method} ${path}`).toBe(status);
  return response;
}

async function login(page: Page) {
  await page.getByLabel('Логин', { exact: true }).fill(adminUsername!);
  await page.getByLabel('Пароль', { exact: true }).fill(adminPassword!);
  const response = await responseAfter(page, 'POST', '/auth/login', 200,
    () => page.getByRole('button', { name: 'Войти', exact: true }).click());
  await expect(page.getByRole('banner').getByText(adminUsername!, { exact: true })).toBeVisible();
  return await response.json() as AuthResponse;
}

async function captureViews(page: Page, info: TestInfo, name: string) {
  const original = page.viewportSize();
  for (const [size, width, height] of [['desktop', 1440, 1000], ['mobile', 390, 844]] as const) {
    await page.setViewportSize({ width, height });
    expect(await page.locator('html').evaluate(element => element.scrollWidth), `${size}: no horizontal overflow`).toBeLessThanOrEqual(width);
    const path = info.outputPath(`${name}-${size}.png`);
    await page.screenshot({ path, fullPage: true, animations: 'disabled' });
    await info.attach(`${name}-${size}`, { path, contentType: 'image/png' });
  }
  if (original) await page.setViewportSize(original);
}

function shiftDate(day: string, days: number) {
  return new Date(Date.parse(`${day}T00:00:00Z`) + days * 86400000).toISOString().slice(0, 10);
}

function nextBusinessMidnight(today: string, timezone: string) {
  const tomorrow = shiftDate(today, 1);
  const formatter = new Intl.DateTimeFormat('en-CA', { timeZone: timezone, year: 'numeric', month: '2-digit', day: '2-digit' });
  const dayAt = (instant: number) => {
    const parts = formatter.formatToParts(instant);
    return ['year', 'month', 'day'].map(type => parts.find(part => part.type === type)!.value).join('-');
  };
  // Find the actual date boundary, including offset and DST; never assume a 24-hour local day.
  const utcMidnight = Date.parse(`${tomorrow}T00:00:00Z`);
  let low = utcMidnight - 86400000, high = utcMidnight + 86400000;
  while (high - low > 1) {
    const middle = Math.floor((low + high) / 2);
    if (dayAt(middle) < tomorrow) low = middle;
    else high = middle;
  }
  expect(dayAt(high - 60000)).toBe(today);
  expect(dayAt(high)).toBe(tomorrow);
  return high;
}

test('Unicode-пароли и названия сохраняются без обрезания допустимых символов', async ({ page, baseURL }, info) => {
  await page.goto('/#users');
  const session = await login(page);
  const headers = { Origin: new URL(baseURL!).origin, 'X-CSRF-Token': session.csrf_token };
  const username = `unicode_${randomUUID().replaceAll('-', '').slice(0, 16)}`;
  let userId = '', ruleId = '', userPosts = 0, rulePosts = 0;
  page.on('request', request => {
    if (request.method() !== 'POST') return;
    const path = new URL(request.url()).pathname;
    if (path === '/api/v1/users') userPosts++;
    if (path === '/api/v1/recurring-payments') rulePosts++;
  });
  try {
    await test.step('Четыре emoji отклоняются локально, 64 emoji и буква доходят до настоящего API', async () => {
      await page.getByRole('button', { name: 'Добавить пользователя', exact: true }).first().click();
      const form = page.getByRole('dialog', { name: 'Новый пользователь', exact: true });
      await form.locator('#user-username').fill(username);
      await form.locator('#user-password').fill('😀'.repeat(4));
      await form.getByRole('button', { name: 'Добавить пользователя', exact: true }).click();
      await expect(form.getByText('Пароль должен содержать от 8 до 128 символов.', { exact: true })).toBeVisible();
      expect(userPosts).toBe(0);
      const password = '😀'.repeat(64) + 'a';
      await form.locator('#user-password').fill(password);
      await expect(form.locator('#user-password')).toHaveValue(password);
      const created = await responseAfter(page, 'POST', '/users', 201,
        () => form.getByRole('button', { name: 'Добавить пользователя', exact: true }).click());
      userId = (await created.json() as { id: string }).id;
      expect(created.request().postDataJSON().password).toBe(password);
      await expect(form).toHaveCount(0);
      await expect(page.getByRole('row').filter({ hasText: username })).toBeVisible();
      await captureViews(page, info, 'unicode-user');
    });
    await test.step('Лимит названия считает символы, а не UTF-16; сервер сохраняет название полностью', async () => {
      await page.getByRole('link', { name: 'Регулярные', exact: true }).click();
      await page.getByRole('button', { name: 'Добавить платёж', exact: true }).first().click();
      const form = page.getByRole('dialog', { name: 'Новый регулярный платёж', exact: true });
      await form.locator('#recurring-title').fill('🧾'.repeat(201));
      await form.locator('#recurring-amount').fill('100.50');
      await expect(form.getByRole('button', { name: 'Первый срок оплаты', exact: true })).not.toContainText('дд.мм.гггг');
      await form.getByRole('button', { name: 'Добавить платёж', exact: true }).click();
      await expect(form.getByText('Введите название от 1 до 200 символов.', { exact: true })).toBeVisible();
      expect(rulePosts).toBe(0);
      const title = '🧾'.repeat(100) + randomUUID().slice(0, 8);
      await form.locator('#recurring-title').fill(title);
      await expect(form.locator('#recurring-title')).toHaveValue(title);
      const created = await responseAfter(page, 'POST', '/recurring-payments', 201,
        () => form.getByRole('button', { name: 'Добавить платёж', exact: true }).click());
      const rule = await created.json() as { id: string; title: string };
      ruleId = rule.id;
      expect(rule.title).toBe(title);
      await expect(form).toHaveCount(0);
      await expect(page.getByRole('row').filter({ hasText: title })).toBeVisible();
      await captureViews(page, info, 'unicode-title');
    });
  } finally {
    // The isolated stack is disposed on timeout; preserve the original timeout diagnostic.
    if (info.status !== 'timedOut') {
      if (userId) expect((await page.request.delete(`/api/v1/users/${userId}`, { headers })).status()).toBe(204);
      if (ruleId) expect((await page.request.delete(`/api/v1/recurring-payments/${ruleId}`, { headers })).status()).toBe(204);
    }
  }
});

test('запоздавший настоящий 401 не завершает новую сессию после повторного входа', async ({ page, baseURL }, info) => {
  await page.goto('/#payments');
  const session = await login(page);
  const headers = { Origin: new URL(baseURL!).origin, 'X-CSRF-Token': session.csrf_token };
  await expect(page.getByRole('button', { name: 'Обновить список и сводку', exact: true })).toBeEnabled();
  // Revoke the real cookie/session outside the UI, leaving both protected views mounted.
  expect((await page.request.post('/api/v1/auth/logout', { headers })).status()).toBe(204);
  let release: () => void = () => {}, captured = false, completed = false;
  const gate = new Promise<void>(resolve => { release = resolve; });
  await page.route('**/api/v1/payment-occurrences?*', async route => {
    if (captured || route.request().method() !== 'GET') return route.continue();
    const response = await route.fetch();
    expect(response.status()).toBe(401);
    captured = true;
    await gate;
    await route.fulfill({ response });
    completed = true;
  });
  try {
    await test.step('Первый 401 открывает вход, второй настоящий ответ задержан', async () => {
      await page.getByRole('button', { name: 'Обновить список и сводку', exact: true }).click();
      await expect.poll(() => captured).toBe(true);
      await expect(page.getByRole('heading', { name: 'Вход в систему', exact: true })).toBeVisible();
    });
    await test.step('Поздний ответ прежнего запроса не стирает успешный повторный вход', async () => {
      await login(page);
      release();
      await expect.poll(() => completed).toBe(true);
      await page.waitForLoadState('networkidle');
      await expect(page.getByRole('banner').getByText(adminUsername!, { exact: true })).toBeVisible();
      await expect(page.getByRole('heading', { name: 'Вход в систему', exact: true })).toHaveCount(0);
      expect((await page.request.get('/api/v1/auth/me')).status()).toBe(200);
      await captureViews(page, info, 'late-401-session');
    });
  } finally {
    release();
    await page.unrouteAll({ behavior: 'ignoreErrors' });
  }
});

test('смена рабочего дня обновляет просрочку в открытой форме и сохраняет черновик даты', async ({ page, baseURL }, info) => {
  // Setup remains real HTTP + PostgreSQL. Only the read-only day-derived fields are controlled below.
  const auth = await page.request.post('/api/v1/auth/login', {
    headers: { Origin: new URL(baseURL!).origin }, data: { username: adminUsername, password: adminPassword },
  });
  expect(auth.status()).toBe(200);
  const session = await auth.json() as AuthResponse;
  const headers = { Origin: new URL(baseURL!).origin, 'X-CSRF-Token': session.csrf_token };
  const summaryResponse = await page.request.get('/api/v1/payments/summary');
  expect(summaryResponse.status()).toBe(200);
  const summary = await summaryResponse.json() as PaymentSummary;
  expect(summary.timezone).toBe(session.timezone);
  const today = summary.as_of_date, tomorrow = shiftDate(today, 1), draft = shiftDate(today, -1);
  const title = `Смена дня E2E ${randomUUID().slice(0, 8)}`;
  let ruleId = '';
  try {
    const created = await page.request.post('/api/v1/recurring-payments', {
      headers, data: { title, amount: '1500.00', currency: 'RUB', first_due_date: today, periodicity: 'monthly' },
    });
    expect(created.status()).toBe(201);
    ruleId = (await created.json() as { id: string }).id;
    const listing = await page.request.get(`/api/v1/payment-occurrences?recurring_payment_id=${ruleId}&date_from=${today}&date_to=${today}`);
    expect(listing.status()).toBe(200);
    const occurrence = (await listing.json() as { items: PaymentOccurrence[] }).items.find(item => item.due_date === today)!;
    expect(occurrence).toBeDefined();
    let rollover = false, detailReads = 0, collectionReads = 0;
    page.on('request', request => { if (request.method() === 'GET' && new URL(request.url()).pathname === '/api/v1/payment-occurrences') collectionReads++; });
    await page.route(`**/api/v1/payment-occurrences/${occurrence.id}`, async route => {
      if (route.request().method() !== 'GET') return route.continue();
      const response = await route.fetch();
      expect(response.status()).toBe(200);
      const item = await response.json() as PaymentOccurrence;
      detailReads++;
      // Simulate the next business day for this real item; never change the host/database clock.
      await route.fulfill({ response, json: { ...item, is_overdue: rollover, days_late: rollover ? 1 : 0 } });
    });
    const midnight = nextBusinessMidnight(today, session.timezone);
    // Load and edit with timers running so focus/animation frames can settle naturally.
    await page.clock.install({ time: new Date(midnight - 300000) });
    await page.goto(`/#calendar?month=${today.slice(0, 7)}&day=${today}&status=all`);
    await expect(page.locator('.calendar-explanation')).toContainText(session.timezone);
    await page.getByRole('complementary', { name: 'Платежи выбранного дня' }).getByRole('button', { name: new RegExp(`^${title},`) }).click();
    const drawer = page.getByRole('dialog', { name: 'Отметить оплату', exact: true });
    await expect(drawer.getByRole('button', { name: 'Подтвердить оплату', exact: true })).toBeEnabled();
    await drawer.getByRole('button', { name: 'Фактическая дата оплаты', exact: true }).click();
    const calendar = page.getByRole('dialog', { name: 'Календарь: Фактическая дата оплаты', exact: true });
    if (draft.slice(0, 7) !== today.slice(0, 7)) await calendar.getByRole('button', { name: 'Предыдущий месяц', exact: true }).click();
    await calendar.locator(`[data-date="${draft}"]`).click();
    const dateLabel = (value: string) => value.split('-').reverse().join('.');
    await expect(drawer.getByRole('button', { name: 'Фактическая дата оплаты', exact: true })).toContainText(dateLabel(draft));
    await page.clock.pauseAt(new Date(midnight - 50000));
    const readsBefore = detailReads, collectionsBefore = collectionReads;
    rollover = true;
    // Fire the refresh tick at the destination time, without also advancing the new HTTP timeout.
    await page.clock.fastForward(70000);
    await expect.poll(() => detailReads).toBeGreaterThan(readsBefore);
    await expect.poll(() => collectionReads).toBeGreaterThan(collectionsBefore);
    await expect(drawer.locator('#paid-on-hint')).toContainText(dateLabel(tomorrow));
    await expect(drawer.locator('.payment-detail .status')).toHaveText('Просрочено');
    await expect(drawer.locator('dl > div').filter({ hasText: 'Дней опоздания' }).locator('dd')).toHaveText('1');
    await expect(drawer.getByRole('button', { name: 'Фактическая дата оплаты', exact: true })).toContainText(dateLabel(draft));
    await expect(drawer.locator('input[name="paid_on"]')).toHaveValue(draft);
    await page.clock.resume();
    await captureViews(page, info, 'midnight-drawer');
    const patched = await responseAfter(page, 'PATCH', `/payment-occurrences/${occurrence.id}`, 200,
      () => drawer.getByRole('button', { name: 'Подтвердить оплату', exact: true }).click());
    expect(patched.request().postDataJSON()).toEqual({ status: 'paid', paid_on: draft });
    const saved = await patched.json() as PaymentOccurrence;
    expect(saved.paid_on).toBe(draft);
    expect(saved.due_date).toBe(today);
  } finally {
    if (ruleId && info.status !== 'timedOut') {
      expect((await page.request.delete(`/api/v1/recurring-payments/${ruleId}`, { headers })).status()).toBe(204);
    }
  }
});
