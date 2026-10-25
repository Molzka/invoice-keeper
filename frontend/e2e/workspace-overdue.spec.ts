import { expect, test } from '@playwright/test';
import type { PaymentOccurrence, PaymentSummary } from '../src/types/api';

test.use({ reducedMotion: 'reduce' });

test('старые просрочки видны вне месячного фильтра, компактные валюты и мобильная навигация доступны с клавиатуры', async ({ page }, info) => {
  await page.clock.install({ time: new Date('2026-11-10T10:00:00Z') });
  let role = 'admin', failNotice = true;
  const old: PaymentOccurrence = {
    id: '00000000-0000-0000-0000-000000000001', recurring_payment_id: '00000000-0000-0000-0000-000000000010',
    title: 'Аренда офиса · октябрь', amount: '45000.00', currency: 'RUB', due_date: '2026-10-01',
    status: 'unpaid', paid_on: null, is_overdue: true, paid_late: false, days_late: 40,
    recurring_payment_is_active: true, amount_is_custom: false, is_cancelled: false, periodicity: 'monthly',
  };
  const items: PaymentOccurrence[] = [old,
    { ...old, id: '00000000-0000-0000-0000-000000000002', title: 'Годовой контракт · ноябрь', amount: '999999999999.99', due_date: '2026-11-20', is_overdue: false, days_late: 0 },
    { ...old, id: '00000000-0000-0000-0000-000000000003', title: 'Сервер · ноябрь', amount: '29.99', currency: 'USD', due_date: '2026-11-21', is_overdue: false, days_late: 0 },
    { ...old, id: '00000000-0000-0000-0000-000000000004', title: 'Подписка · ноябрь', amount: '12.00', currency: 'EUR', due_date: '2026-11-22', is_overdue: false, days_late: 0 },
    { ...old, id: '00000000-0000-0000-0000-000000000005', title: 'Оплаченная аренда', status: 'paid', paid_on: '2026-10-01', is_overdue: false, days_late: 0 },
    { ...old, id: '00000000-0000-0000-0000-000000000006', title: 'Отменённый период', is_cancelled: true },
  ];
  const summary: PaymentSummary = {
    date_from: '2026-11-01', date_to: '2026-11-30', as_of_date: '2026-11-10', timezone: 'Europe/Moscow',
    totals: {
      RUB: { planned: '999999999999.99', unpaid: '999999999999.99', paid: '0.00', overdue: '0.00' },
      USD: { planned: '29.99', unpaid: '29.99', paid: '0.00', overdue: '0.00' },
      EUR: { planned: '12.00', unpaid: '12.00', paid: '0.00', overdue: '0.00' },
    },
  };
  // Controlled read-only responses isolate UI filtering from the shared test data.
  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url()), params = url.searchParams;
    if (url.pathname === '/api/v1/auth/me') return route.fulfill({ json: {
      user: { id: '00000000-0000-0000-0000-000000000100', username: 'workspace_fixture', role, created_at: '2026-01-01T00:00:00Z' },
      csrf_token: 'workspace-fixture', timezone: 'Europe/Moscow',
    } });
    if (url.pathname === '/api/v1/payments/summary') return route.fulfill({ json: summary });
    if (url.pathname === '/api/v1/payment-occurrences') {
      if (failNotice && params.get('limit') === '1' && params.get('is_overdue') === 'true') {
        return route.fulfill({ status: 503, json: { error: { code: 'API_NOT_AVAILABLE', message: 'Временно недоступно', details: [] } } });
      }
      const filtered = items.filter(item => (!params.get('date_from') || item.due_date >= params.get('date_from')!)
        && (!params.get('date_to') || item.due_date <= params.get('date_to')!)
        && (!params.get('status') || item.status === params.get('status'))
        && (!params.get('currency') || item.currency === params.get('currency'))
        && (params.get('is_overdue') !== 'true' || item.is_overdue)
        && (params.get('include_cancelled') === 'true' || !item.is_cancelled));
      const limit = Number(params.get('limit') || 50), offset = Number(params.get('offset') || 0);
      return route.fulfill({ json: { items: filtered.slice(offset, offset + limit), total: filtered.length, limit, offset } });
    }
    return route.continue();
  });
  await page.goto('/#payments');
  const notice = page.getByRole('complementary', { name: 'Просрочки за всё время' });
  await expect(notice.getByText('Не удалось проверить просрочки.', { exact: true })).toBeVisible();
  await expect(notice).not.toContainText('Просроченных периодов: 0');
  failNotice = false;
  await notice.getByRole('button', { name: 'Повторить загрузку', exact: true }).click();
  await expect(notice).toContainText('Просроченных периодов: 1');

  for (const width of [1440, 768, 390, 320]) {
    await page.setViewportSize({ width, height: 900 });
    expect(await page.locator('html').evaluate(node => node.scrollWidth)).toBeLessThanOrEqual(width);
    await page.screenshot({ path: info.outputPath(`workspace-${width}.png`), fullPage: true, animations: 'disabled' });
  }
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.getByRole('button', { name: 'Срок оплаты с', exact: true }).click();
  await expect(page.getByRole('dialog', { name: 'Календарь: Срок оплаты с', exact: true })).toBeVisible();
  await page.setViewportSize({ width: 320, height: 900 });
  await expect(page.locator('.ik-calendar')).toBeHidden();
  const currencies = page.locator('.currency-compact');
  await expect(currencies).toHaveCount(3);
  await currencies.first().locator('summary').focus();
  await page.keyboard.press('Enter');
  await expect(currencies.first()).toHaveAttribute('open', '');
  await currencies.first().getByRole('link', { name: /^Не оплачено в RUB:/ }).click();
  await expect(page).toHaveURL(/currency=RUB/);
  const filterToggle = page.getByRole('button', { name: 'Фильтры периода и валюты', exact: true });
  await expect(page.getByRole('button', { name: 'Срок оплаты с', exact: true })).toBeHidden();
  await filterToggle.click();
  await expect(page.getByRole('button', { name: 'Срок оплаты с', exact: true })).toBeVisible();
  await filterToggle.click();
  await expect(page.getByRole('button', { name: 'Срок оплаты с', exact: true })).toBeHidden();

  const responsePromise = page.waitForResponse(response => {
    const url = new URL(response.url());
    return url.pathname === '/api/v1/payment-occurrences' && url.searchParams.get('is_overdue') === 'true'
      && url.searchParams.get('limit') !== '1' && !url.searchParams.has('date_from') && !url.searchParams.has('date_to') && !url.searchParams.has('currency');
  });
  await notice.getByRole('link', { name: 'Все просрочки', exact: true }).click();
  expect((await responsePromise).status()).toBe(200);
  await expect(page.getByRole('heading', { level: 1, name: 'Все просрочки' })).toBeVisible();
  await expect(page.getByRole('button', { name: old.title, exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Оплаченная аренда', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Отменённый период', exact: true })).toHaveCount(0);
  await page.reload();
  await expect(page.getByRole('button', { name: old.title, exact: true })).toBeVisible();

  const navigation = page.getByRole('combobox', { name: 'Раздел приложения', exact: true });
  await navigation.focus();
  await page.keyboard.press('End');
  await expect(page.getByRole('option', { name: 'Пользователи', exact: true })).toBeVisible();
  await page.setViewportSize({ width: 1440, height: 900 });
  await expect(page.getByRole('listbox')).toHaveCount(0);
  await page.setViewportSize({ width: 320, height: 900 });
  await navigation.focus();
  await navigation.press('End');
  await page.keyboard.press('Escape');
  await expect(navigation).toBeFocused();
  await navigation.press('Home');
  await page.keyboard.press('Enter');
  await expect(page.getByRole('heading', { level: 1, name: 'Платежи' })).toBeVisible();
  role = 'user';
  await page.reload();
  await navigation.click();
  await expect(page.getByRole('option', { name: 'Пользователи', exact: true })).toHaveCount(0);
  await expect(page.getByRole('option', { name: 'Журнал', exact: true })).toHaveCount(0);
  await page.keyboard.press('Escape');
  await page.getByLabel('Тема оформления', { exact: true }).click();
  await page.getByRole('radio', { name: 'Тёмная', exact: true }).check();
  await expect(page.locator('.ik-select-menu')).toBeHidden();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  expect(await page.locator('html').evaluate(node => node.scrollWidth)).toBeLessThanOrEqual(320);
  await page.screenshot({ path: info.outputPath('workspace-mobile-dark.png'), fullPage: true, animations: 'disabled' });
  items.length = 0;
  for (const totals of Object.values(summary.totals)) Object.assign(totals, { planned: '0.00', paid: '0.00', unpaid: '0.00', overdue: '0.00' });
  await page.reload();
  await expect(page.getByText('Платежей не найдено', { exact: true })).toBeVisible();
  await expect(notice.getByRole('link', { name: 'Все просрочки', exact: true })).toBeVisible();
  await page.screenshot({ path: info.outputPath('workspace-mobile-empty.png'), fullPage: true, animations: 'disabled' });
});
