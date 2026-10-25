import { randomUUID } from 'node:crypto';
import { expect, test } from '@playwright/test';

test.use({ reducedMotion: 'reduce' });

test('выбор интервала обновляет даты и сохраняется в настоящем API', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/#recurring');
  await page.getByLabel('Логин', { exact: true }).fill(process.env.E2E_ADMIN_USERNAME!);
  await page.getByLabel('Пароль', { exact: true }).fill(process.env.E2E_ADMIN_PASSWORD!);
  await page.getByRole('button', { name: 'Войти', exact: true }).click();
  await page.getByRole('button', { name: 'Добавить платёж', exact: true }).first().click();
  const form = page.getByRole('dialog', { name: 'Новый регулярный платёж', exact: true });
  const title = `Сервер команды · ${randomUUID().slice(0, 8)}`;
  await form.getByLabel('Название платежа', { exact: true }).fill(title);
  await form.locator('#recurring-amount').fill('1500');
  await form.getByRole('spinbutton', { name: /^Повторять раз в/ }).fill('0');
  await form.getByRole('button', { name: 'Добавить платёж', exact: true }).click();
  await expect(form.getByText('Введите целое число от 1 до 365.', { exact: true })).toBeVisible();
  await form.getByRole('spinbutton', { name: /^Повторять раз в/ }).fill('2');
  for (const label of ['Дни', 'Месяцы', 'Годы', 'Недели']) {
    await form.getByRole('combobox', { name: 'Периодичность', exact: true }).click();
    await page.getByRole('option', { name: label, exact: true }).click();
    await expect(form.locator('.recurring-preview time')).toHaveCount(3);
  }
  const dates = await form.locator('.recurring-preview time').evaluateAll(elements => elements.map(element => element.getAttribute('datetime')!));
  expect(Date.parse(dates[1]) - Date.parse(dates[0])).toBe(14 * 86400000);
  expect(Date.parse(dates[2]) - Date.parse(dates[1])).toBe(14 * 86400000);
  // Verify the select can also be operated without a pointer.
  await form.getByRole('combobox', { name: 'Периодичность', exact: true }).focus();
  await page.keyboard.press('Enter');
  await page.keyboard.press('Escape');
  await expect(form.getByRole('combobox', { name: 'Периодичность', exact: true })).toBeFocused();
  for (const width of [1440, 390, 320]) {
    await page.setViewportSize({ width, height: 1000 });
    await form.locator('.recurring-preview').scrollIntoViewIfNeeded();
    expect(await page.locator('html').evaluate(element => element.scrollWidth)).toBeLessThanOrEqual(width);
    expect(await form.evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true);
    const path = info.outputPath(`frequency-${width}.png`);
    await page.screenshot({ path, animations: 'disabled' });
    await info.attach(`frequency-${width}`, { path, contentType: 'image/png' });
  }
  const responsePromise = page.waitForResponse(response => response.request().method() === 'POST' && response.url().endsWith('/api/v1/recurring-payments'));
  await form.getByRole('button', { name: 'Добавить платёж', exact: true }).click();
  const response = await responsePromise;
  expect(response.status()).toBe(201);
  expect(response.request().postDataJSON()).toMatchObject({ periodicity: 'weekly', recurrence_interval: 2 });
  const rule = await response.json();
  expect(rule).toMatchObject({ periodicity: 'weekly', recurrence_interval: 2 });
  await expect(form).toHaveCount(0);
  const row = page.getByRole('row').filter({ hasText: title });
  await expect(row).toContainText('Раз в 2 недели');
  await page.reload();
  await expect(row).toContainText('Раз в 2 недели');
  await row.getByRole('button', { name: `Прекратить повторение «${title}»`, exact: true }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Прекратить повторение', exact: true }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  expect(errors).toEqual([]);
});
