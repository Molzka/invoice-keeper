import assert from 'node:assert/strict'
import { Buffer } from 'node:buffer'
import { readFileSync } from 'node:fs'
import { stripTypeScriptTypes } from 'node:module'
import test from 'node:test'
import { URL } from 'node:url'

const encodeModule = source => 'data:text/javascript;base64,' + Buffer.from(source).toString('base64')
const errorModuleUrl = encodeModule(stripTypeScriptTypes(readFileSync(new URL('./errors.ts', import.meta.url), 'utf8'), { mode: 'transform' }))
const { ApiError, isMissingPaymentRoute } = await import(errorModuleUrl)
const mockModuleUrl = encodeModule('export function mockFetch() { throw new Error("Real requests must never fall back to mock") }')
let clientId = 0
async function clientFixture(handler) {
  const calls = [], events = []
  globalThis.__invoiceTestEnv = { VITE_API_MODE: 'real', VITE_API_BASE_URL: '/api/v1' }
  globalThis.window = { dispatchEvent: event => events.push(event.type) }
  globalThis.CustomEvent = class { constructor(type) { this.type = type } }
  globalThis.fetch = async (url, init) => { calls.push({ url, init }); return handler(url, init) }
  let source = stripTypeScriptTypes(readFileSync(new URL('./client.ts', import.meta.url), 'utf8'), { mode: 'transform' })
  source = source.replaceAll('import.meta.env', 'globalThis.__invoiceTestEnv')
  for (const [path, replacement] of [['./errors', errorModuleUrl], ['../mocks/transport', mockModuleUrl]]) {
    source = source.replaceAll("'" + path + "'", JSON.stringify(replacement)).replaceAll('"' + path + '"', JSON.stringify(replacement))
  }
  return { ...(await import(encodeModule(source) + '#client-' + ++clientId)), calls, events }
}
function json(body, status = 200, headers = {}) { return new globalThis.Response(status === 204 ? null : JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json', ...headers } }) }
function serverError(status, code) { return json({ error: { code, message: 'Ответ сервера', details: [] } }, status) }

test('receipt PUT uses cookie and CSRF for exact JSON and raw files, while binary downloads preserve 401 handling', async () => {
  let response = json({ user: { id: 'member', role: 'user' }, csrf_token: 'receipt-token', timezone: 'Europe/Moscow' })
  const { api, calls, events } = await clientFixture(() => response)
  await api.me()
  response = json({ id: 'receipt', kind: 'link', url: 'https://example.com/proof' })
  await api.saveReceiptLink('id /?', 'https://example.com/proof')
  let call = calls.at(-1)
  assert.equal(call.url, '/api/v1/payment-occurrences/id%20%2F%3F/receipt')
  assert.equal(call.init.method, 'PUT'); assert.equal(call.init.credentials, 'include')
  assert.equal(call.init.headers.get('X-CSRF-Token'), 'receipt-token')
  assert.deepEqual(JSON.parse(call.init.body), { url: 'https://example.com/proof' })
  const file = new globalThis.File(['%PDF-1.7 test'], 'Чек.pdf', { type: 'application/pdf' })
  response = json({ id: 'receipt', kind: 'file', filename: file.name })
  await api.saveReceiptFile('id', file)
  call = calls.at(-1)
  assert.equal(call.init.body, file)
  assert.equal(call.init.headers.get('Content-Type'), 'application/pdf')
  assert.equal(call.init.headers.get('X-Filename'), encodeURIComponent('Чек.pdf'))
  assert.equal(call.init.headers.get('X-CSRF-Token'), 'receipt-token')
  response = new globalThis.Response('%PDF-1.7 test', { headers: { 'Content-Type': 'application/pdf' } })
  assert.equal(await (await api.downloadReceipt('id')).text(), '%PDF-1.7 test')
  response = serverError(401, 'AUTH_REQUIRED')
  await assert.rejects(api.downloadReceipt('id'), error => error.status === 401)
  assert.deepEqual(events, ['invoice:unauthorized'])
})

// This is deliberately narrower than a generic 404 detector.
test('only payment collection GET 404s are classified as missing integration routes', () => {
  for (const path of ['/payments/summary', '/payment-occurrences', '/recurring-payments']) {
    assert.equal(isMissingPaymentRoute(new ApiError(404, 'NOT_FOUND', 'Missing', [], { method: 'GET', path })), true)
  }
  for (const [status, method, path] of [[404, 'GET', '/payment-occurrences/item-id'], [404, 'GET', '/recurring-payments/item-id'], [404, 'GET', '/users'], [404, 'POST', '/recurring-payments'], [403, 'GET', '/payments/summary'], [503, 'GET', '/payments/summary'], [401, 'GET', '/payments/summary'], [404, 'GET', '/payments/summary-extra']]) {
    assert.equal(isMissingPaymentRoute(new ApiError(status, 'ERROR', 'Error', [], { method, path })), false)
  }
  assert.equal(isMissingPaymentRoute(new ApiError(404, 'NOT_FOUND', 'Missing')), false)
  assert.equal(isMissingPaymentRoute({ status: 404, request: { method: 'GET', path: '/payments/summary' } }), false)
})

test('JSON and non-JSON collection 404s retain safe method/path metadata and HTTP status', async () => {
  let response = serverError(404, 'NOT_FOUND')
  const { api, calls } = await clientFixture(() => response)
  await assert.rejects(api.getSummary({ date_from: '2026-10-01', date_to: '2026-10-31' }), error => {
    assert.equal(error.code, 'NOT_FOUND'); assert.equal(error.status, 404)
    assert.deepEqual(error.request, { method: 'GET', path: '/payments/summary' })
    assert.equal(isMissingPaymentRoute(error), true); return true
  })
  assert.match(calls[0].url, /\?date_from=2026-10-01&date_to=2026-10-31$/)
  assert.equal(calls[0].init.credentials, 'include')
  assert.equal(calls[0].init.headers.get('Content-Type'), null)
  response = new globalThis.Response('<!doctype html><title>Not found</title>', { status: 404, headers: { 'Content-Type': 'text/html' } })
  await assert.rejects(api.listOccurrences({ status: 'unpaid', limit: 6, offset: 12 }), error => {
    assert.equal(error.status, 404); assert.equal(error.code, 'INVALID_RESPONSE')
    assert.deepEqual(error.request, { method: 'GET', path: '/payment-occurrences' })
    assert.equal(isMissingPaymentRoute(error), true); return true
  })
})

test('item 404 and PERIODS_NOT_READY keep their existing semantics', async () => {
  let response = serverError(404, 'PAYMENT_OCCURRENCE_NOT_FOUND')
  const { api } = await clientFixture(() => response)
  await assert.rejects(api.getOccurrence('missing-id'), error => {
    assert.equal(error.code, 'PAYMENT_OCCURRENCE_NOT_FOUND')
    assert.deepEqual(error.request, { method: 'GET', path: '/payment-occurrences/missing-id' })
    assert.equal(isMissingPaymentRoute(error), false); return true
  })
  response = serverError(503, 'PERIODS_NOT_READY')
  await assert.rejects(api.getSummary(), error => { assert.equal(error.status, 503); assert.equal(error.code, 'PERIODS_NOT_READY'); assert.equal(isMissingPaymentRoute(error), false); return true })
})

test('network and timeout creating POSTs have context and are attempted once', async context => {
  let response = () => { throw new TypeError('Offline') }
  const { api, calls } = await clientFixture((url, init) => response(url, init))
  const payload = { title: 'One create', amount: '1.00', currency: 'RUB', first_due_date: '2026-10-23', periodicity: 'monthly' }
  await assert.rejects(api.createRecurringPayment(payload), error => {
    assert.equal(error.code, 'NETWORK_ERROR'); assert.equal(error.status, 0)
    assert.deepEqual(error.request, { method: 'POST', path: '/recurring-payments' }); return true
  })
  assert.equal(calls.length, 1)
  context.mock.timers.enable({ apis: ['setTimeout'] })
  response = (url, init) => new Promise((resolve, reject) => { init.signal.addEventListener('abort', () => reject(init.signal.reason), { once: true }) })
  const pending = api.createUser({ username: 'example', password: 'example-password' })
  const rejected = assert.rejects(pending, error => {
    assert.equal(error.code, 'TIMEOUT'); assert.equal(error.status, 0)
    assert.deepEqual(error.request, { method: 'POST', path: '/users' }); return true
  })
  context.mock.timers.tick(12000)
  await rejected
  assert.equal(calls.length, 2)
  assert.equal(calls[1].init.credentials, 'include')
})

test('CSRF, bodyless logout and protected 401 handling are preserved', async () => {
  let response = json({ user: { id: 'user-id' }, csrf_token: 'login-token', timezone: 'Europe/Moscow' })
  const { api, calls, events } = await clientFixture(() => response)
  await api.login({ username: 'ivan', password: 'example-password-only' })
  assert.equal(calls.at(-1).init.headers.get('X-CSRF-Token'), null)
  response = json({ user: { id: 'user-id' }, csrf_token: 'me-token', timezone: 'Europe/Moscow' })
  await api.me()
  response = json({})
  await api.updateOccurrence('period-id', { status: 'paid', paid_on: '2026-10-23' })
  assert.equal(calls.at(-1).init.headers.get('X-CSRF-Token'), 'me-token')
  assert.equal(calls.at(-1).init.headers.get('Content-Type'), 'application/json')
  assert.equal(JSON.parse(calls.at(-1).init.body).paid_on, '2026-10-23')
  response = serverError(503, 'SERVICE_UNAVAILABLE')
  await assert.rejects(api.logout())
  response = json({})
  await api.updateOccurrence('period-id', { status: 'unpaid', paid_on: null })
  assert.equal(calls.at(-1).init.headers.get('X-CSRF-Token'), 'me-token')
  response = serverError(401, 'INVALID_CREDENTIALS')
  await assert.rejects(api.login({ username: 'ivan', password: 'wrong' }))
  assert.deepEqual(events, [])
  response = new globalThis.Response('Unauthorized', { status: 401, headers: { 'Content-Type': 'text/plain' } })
  await assert.rejects(api.me())
  assert.deepEqual(events, ['invoice:unauthorized'])
  response = json(null, 204)
  await api.logout()
  assert.equal(calls.at(-1).init.body, undefined)
  assert.equal(calls.at(-1).init.headers.get('Content-Type'), null)
  assert.equal(calls.at(-1).init.headers.get('X-CSRF-Token'), null)
})


test('password change sends exact untrimmed JSON, keeps cookie auth and installs rotated CSRF before resolving', async () => {
  const user = { id: 'user-id', username: 'ivan', role: 'user' }
  let response = json({ user, csrf_token: 'before-change', timezone: 'Europe/Moscow' })
  const { api, calls, events } = await clientFixture(() => response)
  await api.me()
  response = json({ user, csrf_token: 'rotated-token', timezone: 'Europe/Moscow' })
  const payload = { current_password: ' old password ', new_password: ' new password ' }
  const result = await api.changePassword({ ...payload, confirmation: 'must-stay-client-side' })
  assert.equal(result.csrf_token, 'rotated-token')
  const change = calls.at(-1)
  assert.equal(change.url, '/api/v1/auth/change-password')
  assert.equal(change.init.method, 'POST')
  assert.equal(change.init.credentials, 'include')
  assert.equal(change.init.headers.get('X-CSRF-Token'), 'before-change')
  assert.equal(change.init.headers.get('Content-Type'), 'application/json')
  assert.deepEqual(JSON.parse(change.init.body), payload)
  assert.deepEqual(Object.keys(JSON.parse(change.init.body)), ['current_password', 'new_password'])
  response = json({})
  await api.updateOccurrence('period-id', { status: 'unpaid', paid_on: null })
  assert.equal(calls.at(-1).init.headers.get('X-CSRF-Token'), 'rotated-token')
  assert.deepEqual(events, [])
})

test('password field errors retain details and failed changes do not replace the active CSRF token', async () => {
  let response = json({ user: { id: 'user-id' }, csrf_token: 'existing-token', timezone: 'Europe/Moscow' })
  const { api, calls, events } = await clientFixture(() => response)
  await api.me()
  for (const [code, field] of [['CURRENT_PASSWORD_INVALID', 'current_password'], ['NEW_PASSWORD_UNCHANGED', 'new_password']]) {
    response = json({ error: { code, message: 'Ошибка поля', details: [{ field, code, message: 'Проверьте пароль' }] } }, 422)
    await assert.rejects(api.changePassword({ current_password: 'old-password', new_password: 'new-password' }), error => {
      assert.equal(error.status, 422); assert.equal(error.code, code)
      assert.deepEqual(error.details, [{ field, code, message: 'Проверьте пароль' }])
      assert.deepEqual(error.request, { method: 'POST', path: '/auth/change-password' })
      return true
    })
  }
  response = json({})
  await api.updateOccurrence('period-id', { status: 'unpaid', paid_on: null })
  assert.equal(calls.at(-1).init.headers.get('X-CSRF-Token'), 'existing-token')
  assert.deepEqual(events, [])
})

test('rate-limit errors expose strictly parsed bounded Retry-After without replaying password changes', async () => {
  let header = '900'
  const { api, calls } = await clientFixture(() => json({ error: { code: 'PASSWORD_CHANGE_RATE_LIMITED', message: 'Подождите', details: [] } }, 429, header === undefined ? {} : { 'Retry-After': header }))
  for (const [value, expected] of [['900', 900], ['0', 0], ['999999999999999999999', 86400], ['-1', undefined], ['1.5', undefined], ['1e2', undefined], ['Thu, 01 Jan 2037 00:00:00 GMT', undefined], ['garbage', undefined], [undefined, undefined]]) {
    header = value
    const before = calls.length
    await assert.rejects(api.changePassword({ current_password: 'old-password', new_password: 'new-password' }), error => {
      assert.equal(error.code, 'PASSWORD_CHANGE_RATE_LIMITED'); assert.equal(error.status, 429)
      assert.equal(error.retryAfterSeconds, expected); return true
    })
    assert.equal(calls.length, before + 1)
  }
})

test('password network, timeout and CSRF failures never trigger an automatic POST or recovery GET', async context => {
  let response = () => { throw new TypeError('Lost response') }
  const { api, calls, events } = await clientFixture((url, init) => response(url, init))
  const payload = { current_password: 'old-password', new_password: 'new-password' }
  await assert.rejects(api.changePassword(payload), error => error.code === 'NETWORK_ERROR')
  assert.equal(calls.length, 1)
  response = () => serverError(403, 'CSRF_FAILED')
  await assert.rejects(api.changePassword(payload), error => error.code === 'CSRF_FAILED')
  assert.equal(calls.length, 2); assert.deepEqual(events, [])
  context.mock.timers.enable({ apis: ['setTimeout'] })
  response = (url, init) => new Promise((resolve, reject) => { init.signal.addEventListener('abort', () => reject(init.signal.reason), { once: true }) })
  const pending = api.changePassword(payload)
  const rejected = assert.rejects(pending, error => error.code === 'TIMEOUT')
  context.mock.timers.tick(12000)
  await rejected
  assert.equal(calls.length, 3)
  assert.deepEqual(calls.map(call => call.init.method), ['POST', 'POST', 'POST'])
})

test('a password-change 401 follows the existing global session-expiry flow', async () => {
  const { api, calls, events } = await clientFixture(() => serverError(401, 'AUTH_REQUIRED'))
  await assert.rejects(api.changePassword({ current_password: 'old-password', new_password: 'new-password' }), error => error.status === 401)
  assert.equal(calls.length, 1)
  assert.deepEqual(events, ['invoice:unauthorized'])
})


test('real audit requests preserve filters, cookie auth and the server response without demo fallback', async () => {
  const page = { items: [{ id: 'event-id', action: 'payment.paid' }], total: 25, limit: 12, offset: 12 }
  const { api, calls } = await clientFixture(() => json(page))
  const filters = { date_from: '2026-10-01', date_to: '2026-10-31', actor: 'anna', action: 'payment.paid', query: 'Аренда офиса', limit: 12, offset: 12 }
  assert.deepEqual(await api.listAuditEvents(filters), page)
  const call = calls[0]
  const url = new URL(call.url, 'http://localhost')
  assert.equal(url.pathname, '/api/v1/audit-events')
  assert.deepEqual(Object.fromEntries(url.searchParams), Object.fromEntries(Object.entries(filters).map(([key, value]) => [key, String(value)])))
  assert.equal(call.init.method, 'GET')
  assert.equal(call.init.credentials, 'include')
  assert.equal(call.init.headers.get('Content-Type'), null)
  assert.equal(call.init.body, undefined)
  assert.equal(calls.length, 1)
})

test('audit requests omit empty filters and retain backend authorization, availability and network failures', async () => {
  let response = () => json({ items: [], total: 0, limit: 12, offset: 0 })
  const { api, calls, events } = await clientFixture(() => response())
  const filters = { date_from: '', date_to: '', actor: '', action: '', query: '', limit: 12, offset: 0 }
  assert.deepEqual(await api.listAuditEvents(filters), { items: [], total: 0, limit: 12, offset: 0 })
  assert.equal(calls[0].url, '/api/v1/audit-events?limit=12&offset=0')
  for (const [status, code] of [[403, 'FORBIDDEN'], [404, 'NOT_FOUND'], [503, 'SERVICE_UNAVAILABLE'], [401, 'AUTH_REQUIRED']]) {
    response = () => serverError(status, code)
    await assert.rejects(api.listAuditEvents(filters), error => {
      assert.equal(error.status, status)
      assert.equal(error.code, code)
      assert.deepEqual(error.request, { method: 'GET', path: '/audit-events' })
      return true
    })
  }
  response = () => { throw new TypeError('Offline') }
  await assert.rejects(api.listAuditEvents(filters), error => error.code === 'NETWORK_ERROR')
  assert.equal(calls.length, 6)
  assert.deepEqual(events, ['invoice:unauthorized'])
})

test('amount editing uses real exact PATCH routes, cookie and CSRF without leaking form fields', async () => {
  let response = json({ user: { id: 'admin', username: 'admin', role: 'admin' }, csrf_token: 'amount-token', timezone: 'Europe/Moscow' })
  const { api, calls } = await clientFixture(() => response)
  await api.me()
  response = json({ id: 'period', amount: '45000.50', currency: 'USD', amount_is_custom: true })
  const period = await api.updateOccurrenceAmount('period /?', { amount: '45000.50', currency: 'USD', status: 'paid', scope: 'all' })
  assert.equal(period.amount_is_custom, true)
  assert.equal(calls.at(-1).url, '/api/v1/payment-occurrences/period%20%2F%3F/amount')
  assert.equal(calls.at(-1).init.method, 'PATCH'); assert.equal(calls.at(-1).init.credentials, 'include')
  assert.equal(calls.at(-1).init.headers.get('X-CSRF-Token'), 'amount-token')
  assert.deepEqual(JSON.parse(calls.at(-1).init.body), { amount: '45000.50', currency: 'USD' })
  response = json({ payment: { id: 'rule', amount: '42.50', currency: 'EUR', amount_effective_from: '2026-11-01' }, effective_from: '2026-11-01', updated_periods: 2, preserved_custom_periods: 1 })
  const terms = await api.updateRecurringAmount('rule /?', { amount: '42.50', currency: 'EUR', first_due_date: '2000-01-01' })
  assert.equal(terms.updated_periods, 2); assert.equal(terms.preserved_custom_periods, 1)
  assert.equal(calls.at(-1).url, '/api/v1/recurring-payments/rule%20%2F%3F')
  assert.equal(calls.at(-1).init.method, 'PATCH'); assert.equal(calls.at(-1).init.credentials, 'include')
  assert.equal(calls.at(-1).init.headers.get('X-CSRF-Token'), 'amount-token')
  assert.deepEqual(JSON.parse(calls.at(-1).init.body), { amount: '42.50', currency: 'EUR' })
})

test('amount edit failures retain conflicts and field errors and never replay an uncertain PATCH', async context => {
  let response = () => serverError(409, 'PAYMENT_ALREADY_PAID')
  const { api, calls } = await clientFixture((url, init) => response(url, init))
  await assert.rejects(api.updateOccurrenceAmount('period', { amount: '1.00', currency: 'RUB' }), error => error.status === 409 && error.code === 'PAYMENT_ALREADY_PAID')
  response = () => json({ error: { code: 'VALIDATION_ERROR', message: 'Invalid amount', details: [{ field: 'amount', code: 'money_range', message: 'Out of range' }] } }, 422)
  await assert.rejects(api.updateRecurringAmount('rule', { amount: '0.00', currency: 'RUB' }), error => error.details[0].field === 'amount')
  response = () => { throw new TypeError('Disconnected') }
  const start = calls.length
  await assert.rejects(api.updateRecurringAmount('rule', { amount: '1.00', currency: 'RUB' }), error => error.code === 'NETWORK_ERROR')
  assert.equal(calls.length, start + 1)
  context.mock.timers.enable({ apis: ['setTimeout'] })
  response = (url, init) => new Promise((resolve, reject) => { init.signal.addEventListener('abort', () => reject(init.signal.reason), { once: true }) })
  const pending = api.updateOccurrenceAmount('period', { amount: '1.00', currency: 'RUB' })
  const rejected = assert.rejects(pending, error => error.code === 'TIMEOUT' && error.request.path === '/payment-occurrences/period/amount')
  context.mock.timers.tick(12000)
  await rejected
  assert.equal(calls.length, start + 2)
})


test('pending MFA token is isolated until verification and receipt PUT uses the verified session token', async () => {
  let response = json({ mfa_required: true, methods: ['totp', 'telegram', 'recovery'], csrf_token: 'pending-token', expires_at: '2026-10-25T23:59:00Z' })
  const { api, calls, events } = await clientFixture(() => response)
  const challenge = await api.login({ username: 'ivan', password: 'example-password-only' })
  assert.equal(challenge.mfa_required, true)
  assert.equal(calls.at(-1).init.headers.get('X-CSRF-Token'), null)
  response = json({ sent: true, retry_after: 30 })
  await api.sendLoginTelegram()
  assert.equal(calls.at(-1).init.headers.get('X-CSRF-Token'), 'pending-token')
  response = serverError(401, 'MFA_CODE_INVALID')
  await assert.rejects(api.verifyMfa('totp', '123456'), error => error.code === 'MFA_CODE_INVALID')
  assert.deepEqual(events, [])
  assert.equal(calls.at(-1).init.headers.get('X-CSRF-Token'), 'pending-token')
  response = json({ user: { id: 'member', role: 'user' }, csrf_token: 'verified-token', timezone: 'Europe/Moscow' })
  await api.verifyMfa('recovery', 'single-use-code')
  response = json({ id: 'receipt', kind: 'file', filename: 'proof.pdf' })
  const file = new globalThis.File(['%PDF-1.7 test'], 'proof.pdf', { type: 'application/pdf' })
  await api.saveReceiptFile('period', file)
  const saved = calls.at(-1)
  assert.equal(saved.init.method, 'PUT')
  assert.equal(saved.init.headers.get('X-CSRF-Token'), 'verified-token')
  assert.equal(saved.init.headers.get('X-Filename'), 'proof.pdf')
  assert.equal(saved.init.body, file)
})
