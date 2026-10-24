import { randomUUID } from 'node:crypto';
import { expect, test } from '@playwright/test';
import type { PaymentOccurrence } from '../src/types/api';

test.use({ reducedMotion: 'reduce' });

test('дневные итоги, бюджет и подтверждения используют настоящие суммы и периоды', async ({ page, baseURL }, info) => {
  const origin = new URL(baseURL!).origin;
  const auth = await page.request.post('/api/v1/auth/login', {
    headers: { Origin: origin }, data: { username: process.env.E2E_ADMIN_USERNAME, password: process.env.E2E_ADMIN_PASSWORD },
  });
  expect(auth.status()).toBe(200);
  const headers = { Origin: origin, 'X-CSRF-Token': (await auth.json() as { csrf_token: string }).csrf_token };
  const title = `Дневные итоги ${randomUUID().slice(0, 8)}`;
  const items: PaymentOccurrence[] = [];
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  try {
    for (const [currency, amount] of [['RUB', '0.10'], ['RUB', '0.20'], ['USD', '1.25'], ['EUR', '3.40']]) {
      const result = await page.request.post('/api/v1/one-time-payments', {
        headers, data: { title: `${title} ${items.length}`, amount, currency, due_date: '1996-02-29' },
      });
      expect(result.status()).toBe(201);
      items.push(await result.json() as PaymentOccurrence);
    }
    expect((await page.request.patch(`/api/v1/payment-occurrences/${items[0].id}`, {
      headers, data: { status: 'paid', paid_on: '1996-02-29' },
    })).status()).toBe(200);

    await page.goto('/#calendar?month=1996-02&day=1996-02-29');
    const totals = page.getByRole('region', { name: 'Итоги за 29.02.1996', exact: true });
    await expect(totals).toBeVisible();
    const rubles = totals.locator('dl > div').filter({ hasText: 'RUB' });
    await expect(rubles.locator('strong')).toHaveText(/0,30/);
    await expect(rubles).toContainText('Оплачено: 0,10');
    await expect(rubles).toContainText('К оплате: 0,20');
    await expect(rubles).toContainText('Из них просрочено: 0,20');
    await expect(totals.locator('dl > div').filter({ hasText: 'USD' }).locator('strong')).toHaveText(/1,25/);
    await expect(totals.locator('dl > div').filter({ hasText: 'EUR' }).locator('strong')).toHaveText(/3,40/);
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: 1000 });
      await expect(totals).toBeVisible();
      expect(await page.locator('html').evaluate(el => el.scrollWidth)).toBeLessThanOrEqual(width);
      const path = info.outputPath(`daily-totals-${width}.png`);
      await page.screenshot({ path, fullPage: true });
      await info.attach(`daily-totals-${width}`, { path, contentType: 'image/png' });
    }
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto('/#budget?mode=year&year=1996');
    await expect(page.getByRole('heading', { name: 'Бюджет', exact: true })).toBeVisible();
    await expect(page.locator('.budget-currency-card[data-currency="RUB"] .budget-total')).toContainText('0,30');
    await expect(page.getByRole('heading', { name: 'По месяцам', exact: true })).toBeVisible();

    await page.goto(`/#receipts?query=${encodeURIComponent(items[0].title)}`);
    await page.getByRole('button', { name: 'Добавить материал', exact: true }).click();
    const receipt = page.getByRole('dialog', { name: 'Чек или ссылка', exact: true });
    await receipt.getByLabel('HTTPS-ссылка', { exact: true }).fill('https://example.org/invoice-proof');
    await receipt.getByRole('button', { name: 'Прикрепить', exact: true }).click();
    await expect(receipt.getByRole('link', { name: 'Открыть ссылку' })).toHaveAttribute('href', 'https://example.org/invoice-proof');
    await receipt.getByRole('button', { name: 'Файл', exact: true }).click();
    const file = Buffer.from('%PDF-1.4\n% isolated receipt fixture\n%%EOF');
    await receipt.getByLabel('PDF, PNG или JPEG до 5 МиБ').setInputFiles({ name: 'proof.pdf', mimeType: 'application/pdf', buffer: file });
    await receipt.getByRole('button', { name: 'Заменить подтверждение', exact: true }).click();
    await expect(receipt.getByText('proof.pdf', { exact: true })).toBeVisible();
    const [download] = await Promise.all([
      page.waitForEvent('download'), receipt.getByRole('button', { name: 'Скачать файл', exact: true }).click(),
    ]);
    expect(download.suggestedFilename()).toBe('proof.pdf');
    const response = await page.request.get(`/api/v1/payment-occurrences/${items[0].id}/receipt/file`);
    expect(await response.body()).toEqual(file);
    await receipt.getByRole('button', { name: 'Удалить', exact: true }).click();
    await receipt.getByRole('button', { name: 'Удалить подтверждение', exact: true }).click();
    await expect(receipt.getByText('К этому периоду ещё не прикреплено подтверждение.', { exact: true })).toBeVisible();
    expect((await (await page.request.get(`/api/v1/payment-occurrences/${items[0].id}`)).json() as PaymentOccurrence).status).toBe('paid');
    expect(errors).toEqual([]);
  } finally {
    if (info.status !== 'timedOut') for (const item of items) {
      await page.request.patch(`/api/v1/payment-occurrences/${item.id}`, { headers, data: { status: 'unpaid', paid_on: null } });
      await page.request.delete(`/api/v1/payment-occurrences/${item.id}`, { headers });
    }
  }
});
