import { createHmac, randomUUID } from 'node:crypto';
import { expect, test } from '@playwright/test';
import type { Page, TestInfo } from '@playwright/test';
import type { AuthResponse, MfaChallenge } from '../src/types/api';

const adminUsername = process.env.E2E_ADMIN_USERNAME!;
const adminPassword = process.env.E2E_ADMIN_PASSWORD!;
test.use({ reducedMotion: 'reduce' });

async function responseAfter(page: Page, method: string, path: string, status: number, action: () => Promise<unknown>) {
  const [response] = await Promise.all([
    page.waitForResponse(value => value.request().method() === method && new URL(value.url()).pathname === `/api/v1${path}`),
    action(),
  ]);
  expect(response.status(), `${method} ${path}`).toBe(status);
  return response;
}
async function login(page: Page, username: string, password: string) {
  await page.getByLabel('Логин', { exact: true }).fill(username);
  await page.getByLabel('Пароль', { exact: true }).fill(password);
  return responseAfter(page, 'POST', '/auth/login', 200, () => page.getByRole('button', { name: 'Войти', exact: true }).click());
}
async function capture(page: Page, info: TestInfo, name: string) {
  for (const [size, width, height] of [['desktop', 1440, 1000], ['mobile', 390, 844]] as const) {
    await page.setViewportSize({ width, height });
    expect(await page.locator('html').evaluate(element => element.scrollWidth)).toBeLessThanOrEqual(width);
    const path = info.outputPath(`${name}-${size}.png`);
    await page.screenshot({ path, fullPage: await page.getByRole('dialog').count() === 0, animations: 'disabled' });
    await info.attach(`${name}-${size}`, { path, contentType: 'image/png' });
  }
  await page.setViewportSize({ width: 1440, height: 1000 });
}
/** A real authenticator code for the ephemeral enrollment created by this browser. */
function totp(secret: string) {
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
  const bits = [...secret].map(char => alphabet.indexOf(char).toString(2).padStart(5, '0')).join('');
  const key = Buffer.from((bits.match(/.{8}/g) || []).map(byte => Number.parseInt(byte, 2)));
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(Date.now() / 30000)));
  const digest = createHmac('sha1', key).update(counter).digest();
  return ((digest.readUInt32BE(digest[19] & 15) & 0x7fffffff) % 1000000).toString().padStart(6, '0');
}

test('заявка с локальной CAPTCHA, одобрение, добровольная TOTP и одноразовое восстановление', async ({ page, browser, baseURL }, info) => {
  test.setTimeout(90_000);
  const username = `access_${randomUUID().replaceAll('-', '').slice(0, 16)}`;
  const password = `employee-${randomUUID()}`;
  const adminContext = await browser.newContext({ baseURL });
  const admin = await adminContext.newPage();
  let userId = '';
  let adminSession: AuthResponse | undefined;
  try {
    await page.goto('/');
    await page.getByRole('link', { name: 'Нет доступа? Отправить заявку' }).click();
    await expect(page.getByRole('heading', { name: 'Запросить доступ', exact: true })).toBeVisible();
    await page.goBack();
    await expect(page.getByRole('heading', { name: 'Вход в систему', exact: true })).toBeVisible();
    await page.goForward();
    await page.getByLabel('Логин', { exact: true }).fill(username);
    await page.getByLabel('Пароль', { exact: true }).fill(password);
    await page.getByLabel('Повторите пароль', { exact: true }).fill(password);
    await page.getByLabel('Имя или сообщение администратору').fill('Анна — бухгалтерия. Нужен доступ к срокам и отметкам оплаты.');
    // Solve the bundled widget against the actual single-use server challenge, without bypassing CAPTCHA.
    await responseAfter(page, 'GET', '/registration/challenge', 200,
      () => page.locator('altcha-widget').getByText('Я не робот', { exact: true }).click());
    await expect(page.locator('altcha-widget').getByRole('checkbox')).toBeChecked();
    await expect(page.getByRole('button', { name: 'Отправить заявку', exact: true })).toBeEnabled();
    await capture(page, info, 'registration');
    await responseAfter(page, 'POST', '/registration/requests', 202,
      () => page.getByRole('button', { name: 'Отправить заявку', exact: true }).click());
    await expect(page.getByRole('heading', { name: 'Заявка отправлена' })).toBeVisible();
    expect((await page.request.get('/api/v1/payment-occurrences')).status()).toBe(401);
    await page.getByRole('button', { name: 'Вернуться ко входу', exact: true }).click();
    await page.getByLabel('Логин', { exact: true }).fill(username);
    await page.getByLabel('Пароль', { exact: true }).fill(password);
    await responseAfter(page, 'POST', '/auth/login', 401, () => page.getByRole('button', { name: 'Войти', exact: true }).click());

    await admin.goto('/#users');
    adminSession = await (await login(admin, adminUsername, adminPassword)).json() as AuthResponse;
    await expect(admin.getByRole('button', { name: 'Безопасность', exact: true })).toHaveCount(0);
    await admin.getByRole('button', { name: 'Заявки', exact: true }).click();
    await admin.getByRole('button', { name: `Одобрить заявку ${username}`, exact: true }).click();
    const decision = admin.getByRole('dialog', { name: 'Предоставить доступ?', exact: true });
    await capture(admin, info, 'registration-moderation');
    await decision.getByRole('button', { name: 'Одобрить и создать аккаунт', exact: true }).click();
    await expect(decision).toHaveCount(0);

    const session = await (await login(page, username, password)).json() as AuthResponse;
    userId = session.user.id;
    await expect(page.getByRole('button', { name: 'Не сейчас', exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Не сейчас', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'Платежи', exact: true })).toBeVisible();
    expect((await page.request.get('/api/v1/payment-occurrences')).status()).toBe(200);
    await page.getByRole('button', { name: 'Безопасность', exact: true }).click();
    const security = page.getByRole('dialog', { name: 'Безопасность', exact: true });
    await expect(security.getByText('Дополнительная защита не подключена', { exact: true })).toBeVisible();
    await capture(page, info, 'security-optional');
    await security.locator('.security-row').filter({ hasText: 'Приложение-аутентификатор' }).getByRole('button', { name: 'Подключить', exact: true }).click();
    await security.getByLabel('Текущий пароль', { exact: true }).fill(password);
    const setup = await responseAfter(page, 'POST', '/auth/security/totp/setup', 200,
      () => security.getByRole('button', { name: 'Подключить приложение', exact: true }).click());
    const secret = (await setup.json() as { secret: string }).secret;
    await expect(security.getByRole('img', { name: 'QR-код для подключения приложения-аутентификатора' })).toBeVisible();
    await security.getByLabel('Код подтверждения', { exact: true }).fill(totp(secret));
    const confirmation = await responseAfter(page, 'POST', '/auth/security/totp/confirm', 200,
      () => security.getByRole('button', { name: 'Подключить защиту', exact: true }).click());
    const recovery = (await confirmation.json() as { recovery_codes: string[] }).recovery_codes;
    expect(recovery).toHaveLength(10);
    await expect(security.getByRole('button', { name: 'Закрыть панель' })).toBeDisabled();
    await security.getByRole('checkbox', { name: 'Я сохранил резервные коды' }).check();
    await security.getByRole('button', { name: 'Готово', exact: true }).click();
    await expect(security.getByText('Вход защищён', { exact: true })).toBeVisible();
    await capture(page, info, 'security-enabled');
    await security.getByRole('button', { name: 'Закрыть панель' }).click();
    await page.getByRole('button', { name: 'Выйти из системы' }).click();

    const pending = await (await login(page, username, password)).json() as MfaChallenge;
    expect(pending.mfa_required).toBe(true);
    await expect(page.getByRole('heading', { name: 'Подтвердите вход', exact: true })).toBeVisible();
    expect((await page.request.get('/api/v1/payment-occurrences')).status()).toBe(401);
    // Another tab replaces the shared pending cookie; this form still holds its old CSRF token.
    const replaced = await page.request.post('/api/v1/auth/login', {
      headers: { Origin: new URL(baseURL!).origin }, data: { username, password },
    });
    expect(replaced.status()).toBe(200);
    expect((await replaced.json() as MfaChallenge).mfa_required).toBe(true);
    await responseAfter(page, 'POST', '/auth/mfa/cancel', 403,
      () => page.getByRole('button', { name: 'Вернуться ко входу', exact: true }).click());
    await expect(page.getByRole('heading', { name: 'Вход в систему', exact: true })).toBeVisible();
    await login(page, username, password);
    await expect(page.getByRole('heading', { name: 'Подтвердите вход', exact: true })).toBeVisible();
    await page.getByLabel('Способ подтверждения').selectOption('recovery');
    await page.getByLabel('Резервный код', { exact: true }).fill('not-a-valid-code');
    await responseAfter(page, 'POST', '/auth/mfa/verify', 422,
      () => page.getByRole('button', { name: 'Подтвердить вход', exact: true }).click());
    await capture(page, info, 'mfa-challenge');
    await page.getByLabel('Резервный код', { exact: true }).fill(recovery[0]);
    await responseAfter(page, 'POST', '/auth/mfa/verify', 200,
      () => page.getByRole('button', { name: 'Подтвердить вход', exact: true }).click());
    await expect(page.getByRole('heading', { name: 'Платежи', exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Выйти из системы' }).click();
    await login(page, username, password);
    await page.getByLabel('Способ подтверждения').selectOption('recovery');
    await page.getByLabel('Резервный код', { exact: true }).fill(recovery[0]);
    await responseAfter(page, 'POST', '/auth/mfa/verify', 422,
      () => page.getByRole('button', { name: 'Подтвердить вход', exact: true }).click());
    await page.getByLabel('Резервный код', { exact: true }).fill(recovery[1]);
    await responseAfter(page, 'POST', '/auth/mfa/verify', 200,
      () => page.getByRole('button', { name: 'Подтвердить вход', exact: true }).click());
    await page.getByRole('button', { name: 'Безопасность', exact: true }).click();
    await security.getByRole('button', { name: 'Отключить дополнительную защиту', exact: true }).click();
    await security.getByLabel('Текущий пароль', { exact: true }).fill(password);
    await security.getByLabel('Подтвердить с помощью').selectOption('recovery');
    await security.getByLabel('Резервный код', { exact: true }).fill(recovery[2]);
    await responseAfter(page, 'POST', '/auth/security/disable', 200,
      () => security.getByRole('button', { name: 'Отключить дополнительную защиту', exact: true }).click());
    await expect(security.getByText('Дополнительная защита не подключена', { exact: true })).toBeVisible();
  } finally {
    if (adminSession) {
      const headers = { Origin: new URL(baseURL!).origin, 'X-CSRF-Token': adminSession.csrf_token };
      if (!userId) {
        const users = await admin.request.get('/api/v1/users?limit=100');
        if (users.ok()) userId = ((await users.json()) as { items: { id: string; username: string }[] }).items.find(user => user.username === username)?.id || '';
      }
      if (userId) expect((await admin.request.delete(`/api/v1/users/${userId}`, { headers })).status()).toBe(204);
    }
    await adminContext.close();
  }
});
