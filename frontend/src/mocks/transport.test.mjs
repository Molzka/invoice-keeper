import assert from 'node:assert/strict'
import { Buffer } from 'node:buffer'
import { readFileSync } from 'node:fs'
import { stripTypeScriptTypes } from 'node:module'
import test from 'node:test'
import { URL } from 'node:url'

const encodeModule = source => 'data:text/javascript;base64,' + Buffer.from(source).toString('base64')
const tsSource = path => stripTypeScriptTypes(readFileSync(new URL(path, import.meta.url), 'utf8'), { mode: 'transform' })
const demoUrl = encodeModule(tsSource('../config/demo.ts'))
const replaceModule = (source, path, replacement) => source.replaceAll("'" + path + "'", JSON.stringify(replacement)).replaceAll('"' + path + '"', JSON.stringify(replacement))
const fixturesUrl = encodeModule(replaceModule(tsSource('./fixtures.ts'), '../config/demo', demoUrl))
const activityTypesUrl = encodeModule(tsSource('../types/activity.ts'))
const activityUrl = encodeModule(replaceModule(replaceModule(tsSource('./activity.ts'), '../config/demo', demoUrl), '../types/activity', activityTypesUrl))
let fixtureId = 0
async function fixture(context, username = 'ivan', scenario = '') {
  context.mock.timers.enable({ apis: ['setTimeout', 'Date'], now: 1792742400000 })
  const storage = new Map([['invoice-keeper.demo-session.v1', username]])
  const sessionWrites = []
  globalThis.localStorage = {
    getItem: key => storage.get(key) ?? null,
    setItem: (key, value) => { sessionWrites.push([key, value]); storage.set(key, value) },
    removeItem: key => storage.delete(key),
  }
  globalThis.window = { location: { origin: 'http://localhost', search: scenario ? '?scenario=' + scenario : '' } }
  let source = replaceModule(tsSource('./transport.ts'), './fixtures', fixturesUrl)
  source = replaceModule(source, '../config/demo', demoUrl)
  source = replaceModule(source, '../types/activity', activityTypesUrl)
  source = replaceModule(source, './activity', activityUrl)
  const { mockFetch } = await import(encodeModule(source) + '#fixture-' + ++fixtureId)
  async function request(path, init = {}) {
    const pending = mockFetch('/api/v1' + path, init)
    context.mock.timers.tick(180)
    return pending
  }
  const get = path => request(path)
  const post = (path, body, token) => request(path, { method: 'POST', headers: { 'Content-Type': 'application/json', ...(token ? { 'X-CSRF-Token': token } : {}) }, ...(body === undefined ? {} : { body: JSON.stringify(body) }) })
  return { get, post, request, sessionWrites }
}

for (const [username, oldPassword] of [['admin', 'Admin123!'], ['ivan', 'example-password-only']]) {
  test(username === 'admin' ? 'mock protects the administrator password' : 'mock changes own password for user, rotates CSRF and accepts only the exact new secret afterward', async context => {
    const { get, post, sessionWrites } = await fixture(context, username)
    const before = await (await get('/auth/me')).json()
    const newPassword = '  new secret  '
    const changed = await post('/auth/change-password', { current_password: oldPassword, new_password: newPassword }, before.csrf_token)
    if (username === 'admin') {
      assert.equal(changed.status, 403)
      assert.equal((await changed.json()).error.code, 'ADMIN_ACCOUNT_PROTECTED')
      return
    }
    assert.equal(changed.status, 200)
    const after = await changed.json()
    assert.equal(after.user.id, before.user.id)
    assert.equal(after.user.role, before.user.role)
    assert.notEqual(after.csrf_token, before.csrf_token)
    assert.deepEqual(Object.keys(after).sort(), ['csrf_token', 'timezone', 'user'])
    const stale = await post('/auth/logout', undefined, before.csrf_token)
    assert.equal(stale.status, 403)
    assert.equal((await stale.json()).error.code, 'CSRF_FAILED')
    assert.equal((await get('/auth/me')).status, 200)
    assert.equal((await post('/auth/logout', undefined, after.csrf_token)).status, 204)
    assert.equal((await post('/auth/login', { username, password: oldPassword })).status, 401)
    assert.equal((await post('/auth/login', { username, password: newPassword.trim() })).status, 401)
    assert.equal((await post('/auth/login', { username, password: newPassword })).status, 200)
    assert.deepEqual(sessionWrites, [['invoice-keeper.demo-session.v1', username]])
  })
}

test('mock rejects query/extra fields, enforces password bounds and keeps error fields distinct', async context => {
  const { get, post } = await fixture(context)
  const { csrf_token: token } = await (await get('/auth/me')).json()
  const valid = { current_password: 'example-password-only', new_password: 'new-password' }
  for (const [path, body, field] of [
    ['/auth/change-password?confirmation=x', valid, 'query.confirmation'],
    ['/auth/change-password', { ...valid, confirmation: 'new-password' }, 'confirmation'],
    ['/auth/change-password', { ...valid, current_password: '' }, 'current_password'],
    ['/auth/change-password', { ...valid, current_password: 'x'.repeat(129) }, 'current_password'],
    ['/auth/change-password', { ...valid, current_password: null }, 'current_password'],
    ['/auth/change-password', { ...valid, new_password: 'short' }, 'new_password'],
    ['/auth/change-password', { ...valid, new_password: '😀'.repeat(129) }, 'new_password'],
    ['/auth/change-password', { ...valid, new_password: 12345678 }, 'new_password'],
  ]) {
    const response = await post(path, body, token)
    assert.equal(response.status, 422)
    assert.equal((await response.json()).error.details[0].field, field)
  }
  const wrong = await post('/auth/change-password', { ...valid, current_password: 'x' }, token)
  assert.equal(wrong.status, 422)
  const wrongError = (await wrong.json()).error
  assert.equal(wrongError.code, 'CURRENT_PASSWORD_INVALID')
  assert.equal(wrongError.details[0].field, 'current_password')
  const unchanged = await post('/auth/change-password', { ...valid, new_password: valid.current_password }, token)
  assert.equal(unchanged.status, 422)
  const unchangedError = (await unchanged.json()).error
  assert.equal(unchangedError.code, 'NEW_PASSWORD_UNCHANGED')
  assert.equal(unchangedError.details[0].field, 'new_password')
  const unicode = await post('/auth/change-password', { ...valid, new_password: '😀'.repeat(128) }, token)
  assert.equal(unicode.status, 200)
})

test('mock limiter counts wrong-current and successful changes per user, independently of login and CSRF failures', async context => {
  const { get, post } = await fixture(context)
  for (let attempt = 0; attempt < 6; attempt++) assert.equal((await post('/auth/login', { username: 'admin', password: 'incorrect' })).status, 401)
  const { csrf_token: token } = await (await get('/auth/me')).json()
  for (let attempt = 0; attempt < 6; attempt++) assert.equal((await post('/auth/change-password', { current_password: 'example-password-only', new_password: 'new-password' }, 'stale-token')).status, 403)
  const changed = await post('/auth/change-password', { current_password: 'example-password-only', new_password: 'new-password' }, token)
  assert.equal(changed.status, 200)
  const { csrf_token: rotated } = await changed.json()
  for (let attempt = 0; attempt < 4; attempt++) {
    const invalid = await post('/auth/change-password', { current_password: 'wrong-password', new_password: 'next-password' }, rotated)
    assert.equal(invalid.status, 422)
    assert.equal((await invalid.json()).error.code, 'CURRENT_PASSWORD_INVALID')
  }
  const limited = await post('/auth/change-password', { current_password: 'new-password', new_password: 'next-password' }, rotated)
  assert.equal(limited.status, 429)
  assert.equal((await limited.json()).error.code, 'PASSWORD_CHANGE_RATE_LIMITED')
  assert.ok(Number(limited.headers.get('Retry-After')) > 0)
  assert.ok(Number(limited.headers.get('Retry-After')) <= 900)
  context.mock.timers.tick(15 * 60 * 1000)
  assert.equal((await post('/auth/change-password', { current_password: 'new-password', new_password: 'next-password' }, rotated)).status, 200)
})

test('mock response-loss and stale-CSRF scenarios recover with me while preserving unknown password outcome', async context => {
  const { get, post } = await fixture(context, 'ivan', 'password-network')
  const before = await (await get('/auth/me')).json()
  await assert.rejects(post('/auth/change-password', { current_password: 'example-password-only', new_password: 'new-password' }, before.csrf_token), error => error instanceof TypeError)
  const recovered = await (await get('/auth/me')).json()
  assert.notEqual(recovered.csrf_token, before.csrf_token)
  const previous = await post('/auth/change-password', { current_password: 'example-password-only', new_password: 'other-password' }, recovered.csrf_token)
  assert.equal((await previous.json()).error.code, 'CURRENT_PASSWORD_INVALID')
  assert.equal((await post('/auth/change-password', { current_password: 'new-password', new_password: 'other-password' }, recovered.csrf_token)).status, 200)
})

test('mock stale-CSRF scenario rejects the first change without changing the secret', async context => {
  const { get, post } = await fixture(context, 'ivan', 'password-csrf')
  const before = await (await get('/auth/me')).json()
  const rejected = await post('/auth/change-password', { current_password: 'example-password-only', new_password: 'new-password' }, before.csrf_token)
  assert.equal(rejected.status, 403)
  assert.equal((await rejected.json()).error.code, 'CSRF_FAILED')
  const recovered = await (await get('/auth/me')).json()
  assert.notEqual(recovered.csrf_token, before.csrf_token)
  assert.equal((await post('/auth/change-password', { current_password: 'example-password-only', new_password: 'new-password' }, recovered.csrf_token)).status, 200)
})


test('mock account-switch scenario rejects the old form and me returns the other account without changing either password', async context => {
  const { get, post } = await fixture(context, 'ivan', 'password-account-changed')
  const before = await (await get('/auth/me')).json()
  const rejected = await post('/auth/change-password', { current_password: 'example-password-only', new_password: 'must-not-be-saved' }, before.csrf_token)
  assert.equal(rejected.status, 403)
  assert.equal((await rejected.json()).error.code, 'CSRF_FAILED')
  const recovered = await (await get('/auth/me')).json()
  assert.equal(recovered.user.username, 'admin')
  assert.notEqual(recovered.user.id, before.user.id)
  assert.notEqual(recovered.csrf_token, before.csrf_token)
  assert.equal((await post('/auth/logout', undefined, recovered.csrf_token)).status, 204)
  for (const [username, password] of [['admin', 'Admin123!'], ['ivan', 'example-password-only']]) {
    assert.equal((await post('/auth/login', { username, password: 'must-not-be-saved' })).status, 401)
    const login = await post('/auth/login', { username, password })
    assert.equal(login.status, 200)
    const authenticated = await login.json()
    assert.equal((await post('/auth/logout', undefined, authenticated.csrf_token)).status, 204)
  }
})
