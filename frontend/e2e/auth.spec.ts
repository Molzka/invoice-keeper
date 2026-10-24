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

async function openLogin(page: Page) {
  await responseAfter(page, 'GET', '/auth/me', 401, () => page.goto('/#users'));
  await expect(page.getByRole('heading', { name: 'Вход в систему', exact: true })).toBeVisible();
  await expect(page.getByText('Демонстрация интерфейса', { exact: true })).toHaveCount(0);
}

async function login(page: Page, username: string, password: string, status = 200) {
  await page.getByLabel('Логин', { exact: true }).fill(username);
  await page.getByLabel('Пароль', { exact: true }).fill(password);
  await responseAfter(page, 'POST', '/auth/login', status,
    () => page.getByRole('button', { name: 'Войти', exact: true }).click());
  if (status === 200) {
    await expect(page.getByRole('banner').getByText(username, { exact: true })).toBeVisible();
  } else {
    await expect(page.getByRole('alert')).toHaveText('Неверный логин или пароль');
    await expect(page.getByRole('button', { name: 'Выйти из системы' })).toHaveCount(0);
  }
}

async function expectSignedOutAfterReload(page: Page) {
  await responseAfter(page, 'GET', '/auth/me', 401, () => page.reload());
  await expect(page.getByRole('heading', { name: 'Вход в систему', exact: true })).toBeVisible();
}

test('вход, восстановление сессии и выход во всех вкладках', async ({ page, context }) => {
  await test.step('Неверный пароль отклоняется настоящим API', async () => {
    await openLogin(page);
    await login(page, adminUsername, `wrong-${randomUUID()}`, 401);
  });

  await test.step('Администратор входит, сессия переживает обновление страницы', async () => {
    await login(page, adminUsername, adminPassword);
    await expect(page.getByRole('heading', { name: 'Пользователи', exact: true })).toBeVisible();
    await responseAfter(page, 'GET', '/auth/me', 200, () => page.reload());
    await expect(page.getByRole('heading', { name: 'Пользователи', exact: true })).toBeVisible();
  });

  const anotherTab = await context.newPage();
  await test.step('Новая вкладка восстанавливает ту же серверную сессию', async () => {
    await responseAfter(anotherTab, 'GET', '/auth/me', 200, () => anotherTab.goto('/#users'));
    await expect(anotherTab.getByRole('banner').getByText(adminUsername, { exact: true })).toBeVisible();
  });

  await test.step('Выход подтверждён сервером, обе вкладки теряют доступ', async () => {
    await responseAfter(page, 'POST', '/auth/logout', 204,
      () => page.getByRole('button', { name: 'Выйти из системы' }).click());
    await expect(page.getByRole('heading', { name: 'Вход в систему', exact: true })).toBeVisible();
    await expect(anotherTab.getByRole('heading', { name: 'Вход в систему', exact: true })).toBeVisible();
    await expect(anotherTab.getByRole('heading', { name: 'Пользователи', exact: true })).toHaveCount(0);
    await expectSignedOutAfterReload(page);
    await expectSignedOutAfterReload(anotherTab);
  });
});

test('управление пользователем, ограничения прав и отзыв сессий', async ({ page, browser, baseURL }) => {
  const username = `e2e_${randomUUID().replaceAll('-', '').slice(0, 16)}`;
  const renamed = `${username}_renamed`;
  const password = `initial-${randomUUID()}`;
  const newPassword = `changed-${randomUUID()}`;
  let userPath = '';

  await openLogin(page);
  await login(page, adminUsername, adminPassword);
  await test.step('Администратор создаёт обычного пользователя через форму', async () => {
    await page.getByRole('button', { name: 'Добавить пользователя', exact: true }).first().click();
    const form = page.getByRole('dialog', { name: 'Новый пользователь', exact: true });
    await form.getByRole('textbox', { name: /^Логин/ }).fill(username);
    await form.getByLabel(/^Пароль/).fill(password);
    const response = await responseAfter(page, 'POST', '/users', 201,
      () => form.getByRole('button', { name: 'Добавить пользователя', exact: true }).click());
    const created = await response.json() as { id: string; role: string };
    expect(created.role).toBe('user');
    expect(created.id).toMatch(/^[0-9a-f-]{36}$/);
    userPath = `/users/${created.id}`;
    await expect(page.getByRole('row').filter({ hasText: username })).toBeVisible();
  });

  // Separate cookies keep the administrator and ordinary user signed in independently.
  const userContext = await browser.newContext({ baseURL });
  const userPage = await userContext.newPage();
  try {
    await test.step('Обычному пользователю недоступно управление командой', async () => {
      await openLogin(userPage);
      await login(userPage, username, password);
      await expect(userPage.getByRole('heading', { name: 'Раздел доступен администратору' })).toBeVisible();
      await expect(userPage.getByRole('navigation').getByRole('link', { name: 'Пользователи', exact: true })).toHaveCount(0);
      await expect(userPage.getByRole('button', { name: 'Добавить пользователя', exact: true })).toHaveCount(0);
    });

    await test.step('Смена логина сохраняется и отзывает прежнюю сессию', async () => {
      await page.getByRole('button', { name: `Изменить пользователя ${username}`, exact: true }).click();
      const form = page.getByRole('dialog', { name: 'Изменить пользователя', exact: true });
      await form.getByRole('textbox', { name: /^Логин/ }).fill(renamed);
      await responseAfter(page, 'PATCH', userPath, 200,
        () => form.getByRole('button', { name: 'Сохранить изменения', exact: true }).click());
      await responseAfter(page, 'GET', '/auth/me', 200, () => page.reload());
      await expect(page.getByRole('row').filter({ hasText: renamed })).toBeVisible();
      await expectSignedOutAfterReload(userPage);
      await login(userPage, renamed, password);
    });

    await test.step('Новый пароль отзывает сессию, старый пароль больше не подходит', async () => {
      await page.getByRole('button', { name: `Изменить пользователя ${renamed}`, exact: true }).click();
      const form = page.getByRole('dialog', { name: 'Изменить пользователя', exact: true });
      await form.getByLabel(/^Новый пароль/).fill(newPassword);
      await responseAfter(page, 'PATCH', userPath, 200,
        () => form.getByRole('button', { name: 'Сохранить изменения', exact: true }).click());
      await expect(form).toHaveCount(0);
      await expectSignedOutAfterReload(userPage);
      await login(userPage, renamed, password, 401);
      await login(userPage, renamed, newPassword);
    });

    await test.step('Удаление сохраняется, завершает сессию и запрещает новый вход', async () => {
      await page.getByRole('button', { name: `Удалить пользователя ${renamed}`, exact: true }).click();
      const confirmation = page.getByRole('dialog', { name: 'Удалить пользователя?', exact: true });
      await responseAfter(page, 'DELETE', userPath, 204,
        () => confirmation.getByRole('button', { name: 'Удалить пользователя', exact: true }).click());
      await expect(confirmation).toHaveCount(0);
      await responseAfter(page, 'GET', '/auth/me', 200, () => page.reload());
      await expect(page.getByRole('heading', { name: 'Пригласите первого участника' })).toBeVisible();
      await expect(page.getByRole('row').filter({ hasText: renamed })).toHaveCount(0);
      await expectSignedOutAfterReload(userPage);
      await login(userPage, renamed, newPassword, 401);
    });
  } finally {
    await userContext.close();
  }
});
