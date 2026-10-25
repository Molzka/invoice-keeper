import assert from 'node:assert/strict'
import { Buffer } from 'node:buffer'
import { readFileSync } from 'node:fs'
import { stripTypeScriptTypes } from 'node:module'
import test from 'node:test'
import { URL } from 'node:url'

const encode = source => 'data:text/javascript;base64,' + Buffer.from(source).toString('base64')
const ts = path => stripTypeScriptTypes(readFileSync(new URL(path, import.meta.url), 'utf8'), { mode: 'transform' })
const replace = (source, path, replacement) => source.replaceAll("'" + path + "'", JSON.stringify(replacement)).replaceAll('"' + path + '"', JSON.stringify(replacement))
const demoUrl = encode(ts('../config/demo.ts'))
const typesUrl = encode(ts('../types/activity.ts'))
const fixturesUrl = encode(replace(ts('./fixtures.ts'), '../config/demo', demoUrl))
const activityUrl = encode(replace(replace(ts('./activity.ts'), '../config/demo', demoUrl), '../types/activity', typesUrl))
const { createAuditStore, filterAuditEvents, auditMoscowDate } = await import(activityUrl)
const actor = { id: 'actor-id', username: 'admin' }
const entity = { type: 'payment', id: 'rule-id', title: 'Аренда офиса' }
const filters = { date_from: '', date_to: '', actor: '', action: '', query: '', limit: 12, offset: 0 }
let sequence = 0

async function fixture(context, username = 'admin', scenario = '') {
  context.mock.timers.enable({ apis: ['setTimeout', 'Date'], now: 1792742400000 })
  const storage = new Map([['invoice-keeper.demo-session.v1', username]])
  const storageWrites = []
  globalThis.localStorage = { getItem: key => storage.get(key) ?? null, setItem: (key, value) => { storageWrites.push([key, value]); storage.set(key, value) }, removeItem: key => storage.delete(key) }
  globalThis.window = { location: { origin: 'http://localhost', search: scenario ? '?scenario=' + scenario : '' } }
  let source = replace(ts('./transport.ts'), './fixtures', fixturesUrl)
  source = replace(source, '../lib/recurring-inputs', encode(ts('../lib/recurring-inputs.ts')))
  for (const [path, url] of [['../config/demo', demoUrl], ['../types/activity', typesUrl], ['./activity', activityUrl]]) source = replace(source, path, url)
  const { mockFetch } = await import(encode(source) + '#audit-' + ++sequence)
  async function request(path, method = 'GET', body, token) {
    const pending = mockFetch('/api/v1' + path, { method, headers: { 'Content-Type': 'application/json', ...(token ? { 'X-CSRF-Token': token } : {}) }, ...(body === undefined ? {} : { body: JSON.stringify(body) }) })
    context.mock.timers.tick(180)
    return pending
  }
  const list = async () => (await request('/audit-events?limit=100')).json()
  return { request, list, storageWrites }
}

test('audit filters use Moscow dates across UTC midnight and combine actor, action, text and pagination', () => {
  const event = (id, timestamp, name, action, title) => ({ id, occurred_at: timestamp, actor: { ...actor, username: name }, action, entity: { ...entity, title }, changes: [] })
  const events = [event('01', '2026-10-22T20:59:59Z', 'admin', 'payment.created', 'Офис'), event('02', '2026-10-22T21:00:00Z', 'ivan', 'payment.paid', 'Аренда офиса'), event('03', '2026-10-23T20:59:59Z', 'ivan', 'payment.paid', 'Аренда офиса'), event('04', '2026-10-23T21:00:00Z', 'ivan', 'payment.paid', 'Аренда офиса')]
  assert.equal(auditMoscowDate(events[1].occurred_at), '2026-10-23')
  const result = filterAuditEvents(events, { ...filters, date_from: '2026-10-23', date_to: '2026-10-23', actor: 'IV', action: 'payment.paid', query: 'АРЕНДА', limit: 1, offset: 1 })
  assert.equal(result.total, 2)
  assert.deepEqual(result.items.map(item => item.id), ['02'])
  assert.equal(filterAuditEvents(events, { ...filters, query: 'Отмечена оплата' }).total, 3)
})

test('audit store whitelists change fields, copies identities and returns immutable snapshots with stable new-event ordering', () => {
  const store = createAuditStore()
  const source = { actor: { ...actor, password: 'never-store-this' }, entity: { ...entity, csrf_token: 'never-store-that' }, action: 'payment.created', changes: [
    { field: 'password', label: 'Secret', before: 'old-secret', after: 'new-secret' },
    { field: 'username', label: 'Логин', before: 'before', after: 'after' },
    { field: 'status', label: 'Статус', before: 'paid', after: 'paid' },
  ] }
  store.append(source)
  store.append({ actor, entity, action: 'payment.stopped' })
  source.actor.username = 'mutated'
  const result = store.list(filters)
  assert.deepEqual(result.items.map(item => item.action), ['payment.stopped', 'payment.created'])
  assert.equal(result.items[1].actor.username, 'admin')
  assert.deepEqual(result.items[1].changes.map(change => change.field), ['username'])
  assert.doesNotMatch(JSON.stringify(result), /never-store|old-secret|new-secret/)
  result.items[0].entity.title = 'mutated'
  assert.equal(store.list(filters).items[0].entity.title, entity.title)
})

test('demo journal is admin-only, validates filters and has explicit empty/error scenarios', async context => {
  const { request, list } = await fixture(context)
  const seeded = await list()
  assert.ok(seeded.total >= 15)
  assert.equal(seeded.items.length, seeded.total)
  for (const path of ['/audit-events?unexpected=1', '/audit-events?limit=101', '/audit-events?offset=-1', '/audit-events?action=unknown', '/audit-events?date_from=2026-10-24&date_to=2026-10-01']) assert.equal((await request(path)).status, 422)
  const login = await request('/auth/login', 'POST', { username: 'ivan', password: 'example-password-only' })
  assert.equal(login.status, 200)
  assert.equal((await request('/audit-events')).status, 403)
})

test('demo audit has distinguishable empty and temporarily unavailable outcomes', async context => {
  const { request } = await fixture(context, 'admin', 'audit-empty')
  assert.deepEqual(await (await request('/audit-events?limit=12')).json(), { items: [], total: 0, limit: 12, offset: 0 })
  globalThis.window.location.search = '?scenario=audit-error'
  const failed = await request('/audit-events')
  assert.equal(failed.status, 503)
  assert.equal((await failed.json()).error.code, 'AUDIT_TEMPORARILY_UNAVAILABLE')
})

test('successful payment changes log one event, no-ops and rejected mutations log none, history uses recurring ID', async context => {
  const { request, list, storageWrites } = await fixture(context)
  const before = await list()
  const { csrf_token: token } = await (await request('/auth/me')).json()
  const occurrences = await (await request('/payment-occurrences?date_from=2026-10-01&date_to=2026-10-31&status=unpaid&limit=100')).json()
  const target = occurrences.items[0]
  assert.equal((await request('/payment-occurrences/' + target.id, 'PATCH', { status: 'paid', paid_on: '2026-10-24' }, token)).status, 422)
  assert.equal((await list()).total, before.total)
  assert.equal((await request('/payment-occurrences/' + target.id, 'PATCH', { status: 'paid', paid_on: '2026-10-22' }, token)).status, 200)
  let current = await list()
  assert.equal(current.total, before.total + 1)
  assert.equal(current.items[0].action, 'payment.paid')
  assert.equal(current.items[0].entity.id, target.recurring_payment_id)
  assert.equal((await request('/payment-occurrences/' + target.id, 'PATCH', { status: 'paid', paid_on: '2026-10-22' }, token)).status, 200)
  assert.equal((await list()).total, current.total)
  await request('/payment-occurrences/' + target.id, 'PATCH', { status: 'paid', paid_on: '2026-10-23' }, token)
  assert.equal((await list()).items[0].action, 'payment.date_changed')
  await request('/payment-occurrences/' + target.id, 'PATCH', { status: 'unpaid', paid_on: null }, token)
  assert.equal((await list()).items[0].action, 'payment.unpaid')
  const created = await (await request('/recurring-payments', 'POST', { title: 'Новый платёж', amount: '123.45', currency: 'USD', first_due_date: '2026-10-23', periodicity: 'monthly' }, token)).json()
  assert.equal((await list()).items[0].action, 'payment.created')
  await request('/recurring-payments/' + created.id, 'DELETE', undefined, token)
  current = await list()
  assert.equal(current.items[0].action, 'payment.stopped')
  await request('/recurring-payments/' + created.id, 'DELETE', undefined, token)
  assert.equal((await list()).total, current.total)
  assert.deepEqual(storageWrites, [])
})

test('user changes preserve deleted identity and never put password values or tokens in the journal', async context => {
  const { request, list } = await fixture(context)
  let { csrf_token: token } = await (await request('/auth/me')).json()
  const secret = 'private-demo-value'
  const created = await (await request('/users', 'POST', { username: 'audit_test', password: secret }, token)).json()
  assert.equal((await list()).items[0].action, 'user.created')
  const beforeNoop = (await list()).total
  await request('/users/' + created.id, 'PATCH', { username: 'audit_test', password: secret }, token)
  assert.equal((await list()).total, beforeNoop)
  await request('/users/' + created.id, 'PATCH', { username: 'audit_renamed', password: secret + '2' }, token)
  assert.equal((await list()).items[0].action, 'user.updated')
  await request('/users/' + created.id, 'DELETE', undefined, token)
  const deletion = (await list()).items[0]
  assert.equal(deletion.action, 'user.deleted')
  assert.equal(deletion.entity.title, 'audit_renamed')
  assert.equal(deletion.entity.id, created.id)
  const beforeProtected = (await list()).total
  const protectedChange = await request('/auth/change-password', 'POST', { current_password: 'Admin123!', new_password: secret + '3' }, token)
  assert.equal(protectedChange.status, 403)
  assert.equal((await list()).total, beforeProtected)
  const userLogin = await request('/auth/login', 'POST', { username: 'ivan', password: 'example-password-only' })
  token = (await userLogin.json()).csrf_token
  const changed = await request('/auth/change-password', 'POST', { current_password: 'example-password-only', new_password: secret + '3' }, token)
  assert.equal(changed.status, 200)
  const changedToken = (await changed.json()).csrf_token
  const adminLogin = await request('/auth/login', 'POST', { username: 'admin', password: 'Admin123!' })
  assert.equal(adminLogin.status, 200)
  token = (await adminLogin.json()).csrf_token
  const result = await list()
  assert.equal(result.items[0].action, 'password.changed')
  assert.equal(result.items[0].actor.username, 'ivan')
  assert.deepEqual(result.items[0].changes, [])
  const text = JSON.stringify(result)
  for (const value of [secret, 'Admin123!', 'example-password-only', token, changedToken, 'current_password', 'new_password', 'csrf_token']) assert.equal(text.includes(value), false)
})
