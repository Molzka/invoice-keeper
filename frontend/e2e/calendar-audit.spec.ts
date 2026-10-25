import { randomUUID } from 'node:crypto';
import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';

const adminUsername = process.env.E2E_ADMIN_USERNAME;
const adminPassword = process.env.E2E_ADMIN_PASSWORD;
if (!adminUsername || !adminPassword) {
  throw new Error('Set E2E_ADMIN_USERNAME and E2E_ADMIN_PASSWORD for the disposable test database.');
}

async function responseAfter(
  page: Page, method: string, path: string, status: number, action: () => Promise<unknown>,
) {
  const [response] = await Promise.all([
    page.waitForResponse(value => value.request().method() === method
      && new URL(value.url()).pathname === `/api/v1${path}`),
    action(),
  ]);
  expect(response.status(), `${method} ${path}`).toBe(status);
  return response;
}

test('календарь и журнал используют реальные периоды, оплаты и события подтверждений', async ({ page, browser, baseURL }) => {
  const title = `Календарь E2E ${randomUUID().slice(0, 8)}`;
  const receiptUrl = 'https://example.org/private-receipt?token=e2e-do-not-log';
  const headers = { Origin: new URL(baseURL!).origin, 'X-CSRF-Token': '' };
  let paymentId = '';
  let userId = '';

  await responseAfter(page, 'GET', '/auth/me', 401, () => page.goto('/#calendar'));
  await expect(page.getByText('Демонстрация интерфейса', { exact: true })).toHaveCount(0);
  await page.getByLabel('Логин', { exact: true }).fill(adminUsername);
  await page.getByLabel('Пароль', { exact: true }).fill(adminPassword);
  const login = await responseAfter(page, 'POST', '/auth/login', 200,
    () => page.getByRole('button', { name: 'Войти', exact: true }).click());
  headers['X-CSRF-Token'] = (await login.json() as { csrf_token: string }).csrf_token;
  await expect(page.getByRole('heading', { name: 'Календарь оплат', exact: true })).toBeVisible();

  // Create disposable fixtures through the same authenticated API; never start the worker.
  const summary = await page.request.get('/api/v1/payments/summary');
  expect(summary.status()).toBe(200);
  const today = (await summary.json() as { as_of_date: string }).as_of_date;
  const calendarPath = `/#calendar?month=${today.slice(0, 7)}&day=${today}&status=all`;

  try {
    let occurrenceId = '';
    await test.step('Серверный период появляется в календаре и оплачивается через общую панель', async () => {
      const created = await page.request.post('/api/v1/recurring-payments', {
        headers,
        data: { title, amount: '123.45', currency: 'RUB', first_due_date: today, periodicity: 'monthly' },
      });
      expect(created.status()).toBe(201);
      paymentId = (await created.json() as { id: string }).id;
      const periods = await page.request.get(`/api/v1/payment-occurrences?recurring_payment_id=${paymentId}`);
      expect(periods.status()).toBe(200);
      const occurrence = (await periods.json() as { items: { id: string; due_date: string }[] }).items.find(item => item.due_date === today);
      expect(occurrence).toBeDefined();
      occurrenceId = occurrence!.id;

      await page.goto(calendarPath);
      // This hash can select the already loaded month; an explicit refresh includes API fixtures.
      await responseAfter(page, 'GET', '/payment-occurrences', 200,
        () => page.getByRole('button', { name: 'Обновить календарь', exact: true }).click());
      const day = page.getByRole('complementary', { name: 'Платежи выбранного дня' });
      await responseAfter(page, 'GET', `/payment-occurrences/${occurrenceId}`, 200,
        () => day.getByRole('button', { name: new RegExp(`^${title},`) }).click());
      await page.getByRole('dialog', { name: 'Карточка платежа', exact: true }).getByRole('button', { name: 'Отметить оплату', exact: true }).click();
      const drawer = page.getByRole('dialog', { name: 'Отметить оплату', exact: true });
      await expect(drawer).toBeVisible();
      const paid = await responseAfter(page, 'PATCH', `/payment-occurrences/${occurrenceId}`, 200,
        () => drawer.getByRole('button', { name: 'Подтвердить оплату', exact: true }).click());
      expect((await paid.json() as { status: string; paid_on: string }).status).toBe('paid');
      await expect(drawer).toHaveCount(0);
      await expect(day.getByRole('button', { name: new RegExp(`^${title},.*Оплачено$`) })).toBeVisible();
    });

    await test.step('Журнал загружает настоящий аудит с автором и изменениями оплаты', async () => {
      await responseAfter(page, 'GET', '/audit-events', 200,
        () => page.getByRole('navigation', { name: 'Основная навигация' }).getByRole('link', { name: 'Журнал', exact: true }).click());
      await expect(page.getByRole('heading', { name: 'Журнал действий', exact: true })).toBeVisible();
      await page.getByRole('searchbox', { name: 'Поиск по событиям' }).fill(title);
      await responseAfter(page, 'GET', '/audit-events', 200,
        () => page.getByRole('button', { name: 'Применить', exact: true }).click());
      await expect(page.getByRole('button', { name: `Подробнее: Отметка оплаты, ${title}`, exact: true })).toBeVisible();
      await page.getByRole('button', { name: `Подробнее: Отметка оплаты, ${title}`, exact: true }).click();
      const details = page.getByRole('dialog', { name: 'Подробности события', exact: true });
      await expect(details.getByText(adminUsername, { exact: true })).toBeVisible();
      await expect(details.getByRole('region', { name: 'Изменённые поля' })).toContainText('До: Не оплачено');
      await expect(details.getByRole('region', { name: 'Изменённые поля' })).toContainText('После: Оплачено');
      await details.getByRole('button', { name: 'Закрыть', exact: true }).click();
      await expect(details).toHaveCount(0);
    });

    await test.step('Новые события подтверждений отображаются без приватной ссылки', async () => {
      const updated = await page.request.put(`/api/v1/payment-occurrences/${occurrenceId}/receipt`, {
        headers, data: { url: receiptUrl },
      });
      expect(updated.status()).toBe(200);
      await responseAfter(page, 'GET', '/audit-events', 200,
        () => page.getByRole('button', { name: 'Обновить журнал действий', exact: true }).click());
      await page.getByRole('button', { name: `Подробнее: Изменение подтверждения оплаты, ${title}`, exact: true }).click();
      const details = page.getByRole('dialog', { name: 'Подробности события', exact: true });
      await expect(details.getByRole('region', { name: 'Изменённые поля' })).toContainText('После: Ссылка');
      await expect(page.getByText(receiptUrl, { exact: true })).toHaveCount(0);
      await details.getByRole('button', { name: 'Закрыть', exact: true }).click();
      await expect(details).toHaveCount(0);

      const deleted = await page.request.delete(`/api/v1/payment-occurrences/${occurrenceId}/receipt`, { headers });
      expect(deleted.status()).toBe(204);
      await responseAfter(page, 'GET', '/audit-events', 200,
        () => page.getByRole('button', { name: 'Обновить журнал действий', exact: true }).click());
      await expect(page.getByRole('button', { name: `Подробнее: Удаление подтверждения оплаты, ${title}`, exact: true })).toBeVisible();
      await page.reload();
      await expect(page.getByRole('button', { name: `Подробнее: Удаление подтверждения оплаты, ${title}`, exact: true })).toBeVisible();
      await expect(page.getByRole('searchbox', { name: 'Поиск по событиям' })).toHaveValue(title);
    });

    await test.step('Обычная роль видит календарь, а журнал защищён сервером', async () => {
      const username = `cal_${randomUUID().replaceAll('-', '').slice(0, 16)}`;
      const password = `e2e-${randomUUID()}`;
      const created = await page.request.post('/api/v1/users', { headers, data: { username, password } });
      expect(created.status()).toBe(201);
      userId = (await created.json() as { id: string }).id;
      const userContext = await browser.newContext({ baseURL });
      try {
        const userLogin = await userContext.request.post('/api/v1/auth/login', {
          headers: { Origin: headers.Origin }, data: { username, password },
        });
        expect(userLogin.status()).toBe(200);
        const userPage = await userContext.newPage();
        await userPage.goto(calendarPath);
        await expect(userPage.getByRole('heading', { name: 'Календарь оплат', exact: true })).toBeVisible();
        await expect(userPage.getByRole('complementary', { name: 'Платежи выбранного дня' }).getByRole('button', { name: new RegExp(`^${title},`) })).toBeVisible();
        await expect(userPage.getByRole('navigation', { name: 'Основная навигация' }).getByRole('link', { name: 'Журнал', exact: true })).toHaveCount(0);
        const forbidden = await userContext.request.get('/api/v1/audit-events');
        expect(forbidden.status()).toBe(403);
        expect((await forbidden.json() as { error: { code: string } }).error.code).toBe('FORBIDDEN');
      } finally {
        await userContext.close();
      }
    });
  } finally {
    // On timeout the runner disposes the isolated database; do not mask the original failure.
    if (test.info().status !== 'timedOut') {
      if (userId) await page.request.delete(`/api/v1/users/${userId}`, { headers });
      if (paymentId) await page.request.delete(`/api/v1/recurring-payments/${paymentId}`, { headers });
    }
  }
});
