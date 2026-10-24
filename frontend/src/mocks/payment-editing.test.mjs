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
const baseFixturesUrl = encode(replace(ts('./fixtures.ts'), '../config/demo', demoUrl))
const activityUrl = encode(replace(replace(ts('./activity.ts'), '../config/demo', demoUrl), '../types/activity', typesUrl))
const FIGMA_ID = 'f0000000-1111-4111-8111-000000000003'
let sequence = 0
const cents = value => BigInt(value.replace('.', ''))

test('one-time payments are single periods and deletion preserves a read-only history outside totals', async context => {
  const { request, occurrences } = await fixture(context)
  const before = (await (await request('/payments/summary')).json()).totals.RUB.planned
  const created = await request('/one-time-payments', 'POST', { title: 'One-time expense', amount: '45000.50', currency: 'RUB', due_date: '2026-10-23' })
  assert.equal(created.status, 201)
  const item = await created.json()
  assert.equal(item.periodicity, 'once')
  assert.equal((await occurrences()).filter(row => row.recurring_payment_id === item.recurring_payment_id).length, 1)
  assert.equal((await request('/payment-occurrences/' + item.id, 'DELETE')).status, 204)
  assert.equal((await request('/payment-occurrences/' + item.id, 'DELETE')).status, 204)
  assert.equal((await occurrences()).some(row => row.id === item.id), false)
  const history = (await (await request('/payment-occurrences?include_cancelled=true&limit=100')).json()).items
  assert.equal(history.find(row => row.id === item.id).is_cancelled, true)
  assert.equal((await request('/payment-occurrences/' + item.id, 'PATCH', { status: 'paid', paid_on: '2026-10-23' })).status, 409)
  assert.equal((await (await request('/payments/summary')).json()).totals.RUB.planned, before)
})

test('archive preserves paid periods and deletes unpaid obligations, and members cannot delete', async context => {
  const { request, occurrences, login } = await fixture(context)
  const rows = await occurrences(), paid = rows.find(row => row.status === 'paid')
  assert.equal((await request('/payment-occurrences/' + paid.id, 'DELETE')).status, 409)
  const ruleId = rows.find(row => row.status === 'unpaid').recurring_payment_id
  assert.equal((await request('/recurring-payments/' + ruleId + '/archive', 'POST')).status, 204)
  assert.equal((await occurrences()).some(row => row.recurring_payment_id === ruleId && row.status === 'unpaid'), false)
  assert.equal((await occurrences()).some(row => row.id === paid.id), true)
  await login('ivan', 'example-password-only')
  assert.equal((await request('/payment-occurrences/' + paid.id, 'DELETE')).status, 403)
})

test('budget separates forecast from saved obligations and receipt filters paginate matching server records', async context => {
  const { request, occurrences } = await fixture(context)
  const budget = await request('/payments/budget?year=2027')
  assert.equal(budget.status, 200)
  const report = await budget.json()
  assert.equal(report.months.length, 12)
  for (const total of Object.values(report.totals)) assert.equal(cents(total.planned), cents(total.paid) + cents(total.unpaid) + cents(total.forecast))
  const item = (await occurrences()).find(row => row.status === 'unpaid')
  assert.equal((await request('/payment-occurrences/' + item.id + '/receipt', 'PUT', { url: 'javascript:alert(1)' })).status, 422)
  assert.equal((await request('/payment-occurrences/' + item.id + '/receipt', 'PUT', { url: 'https://example.com/proof' })).status, 200)
  const page = await (await request('/payment-receipts?kind=link&limit=1')).json()
  assert.equal(page.total, 1)
  assert.equal(page.items[0].occurrence.id, item.id)
  assert.equal((await request('/payment-occurrences/' + item.id + '/receipt', 'DELETE')).status, 204)
  assert.equal((await (await request('/payment-receipts?kind=link')).json()).total, 0)
})

async function fixture(context, options = {}) {
  context.mock.timers.enable({ apis: ['setTimeout', 'Date'], now: 1792742400000 })
  const storage = new Map([['invoice-keeper.demo-session.v1', 'admin']])
  globalThis.localStorage = { getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key) }
  globalThis.window = { location: { origin: 'http://localhost', search: '' } }
  // Extra generated periods exercise custom, paid and ordinary future snapshots together.
  const fixturesUrl = options.futurePeriods ? encode(`import { createFixtures as base } from ${JSON.stringify(baseFixturesUrl)};
    export { ADMIN_ID } from ${JSON.stringify(baseFixturesUrl)};
    export function createFixtures(stress) { const db = base(stress); const next = db.occurrences.find(item => item.recurring_payment_id === '${FIGMA_ID}' && item.due_date === '2026-11-12');
      db.occurrences.push({ ...next, id: 'b0000000-2222-4222-8222-000000000001', due_date: '2026-12-12' }, { ...next, id: 'b0000000-2222-4222-8222-000000000002', due_date: '2027-01-12' }); return db; }`) : baseFixturesUrl
  let source = replace(ts('./transport.ts'), './fixtures', fixturesUrl)
  for (const [path, url] of [['../config/demo', demoUrl], ['../types/activity', typesUrl], ['./activity', activityUrl]]) source = replace(source, path, url)
  const { mockFetch } = await import(encode(source) + '#payment-edit-' + ++sequence)
  let token = ''
  async function request(path, method = 'GET', body, csrf = token) {
    const pending = mockFetch('/api/v1' + path, { method, headers: { 'Content-Type': 'application/json', ...(csrf ? { 'X-CSRF-Token': csrf } : {}) }, ...(body === undefined ? {} : { body: JSON.stringify(body) }) })
    context.mock.timers.tick(180)
    return pending
  }
  async function login(username, password) { const response = await request('/auth/login', 'POST', { username, password }); token = (await response.json()).csrf_token }
  token = (await (await request('/auth/me')).json()).csrf_token
  const occurrences = async () => (await (await request('/payment-occurrences?limit=100')).json()).items
  const audits = async () => (await (await request('/audit-events?limit=100')).json())
  return { request, occurrences, audits, login }
}

test('single unpaid period edit preserves other snapshots and moves exact currency totals', async context => {
  const { request, occurrences, audits } = await fixture(context)
  const before = await occurrences(), item = before.find(row => row.due_date === '2026-10-31')
  const priorAudit = await audits(), priorSummary = await (await request('/payments/summary')).json()
  const response = await request('/payment-occurrences/' + item.id + '/amount', 'PATCH', { amount: '123.45', currency: 'USD' })
  assert.equal(response.status, 200)
  const updated = await response.json()
  assert.equal(updated.amount, '123.45'); assert.equal(updated.currency, 'USD'); assert.equal(updated.amount_is_custom, true)
  assert.equal(updated.status, item.status); assert.equal(updated.paid_on, item.paid_on); assert.equal(updated.due_date, item.due_date)
  assert.deepEqual((await occurrences()).filter(row => row.id !== item.id), before.filter(row => row.id !== item.id))
  const rule = (await (await request('/recurring-payments?limit=100')).json()).items.find(row => row.id === item.recurring_payment_id)
  assert.equal(rule.amount, item.amount); assert.equal(rule.currency, item.currency)
  const totals = (await (await request('/payments/summary')).json()).totals
  for (const field of ['planned', 'unpaid']) {
    assert.equal(cents(totals.RUB[field]), cents(priorSummary.totals.RUB[field]) - cents(item.amount))
    assert.equal(cents(totals.USD[field]), cents(priorSummary.totals.USD[field]) + 12345n)
  }
  assert.deepEqual(totals.EUR, priorSummary.totals.EUR)
  assert.equal((await audits()).total, priorAudit.total + 1)
  const event = (await audits()).items[0]
  assert.equal(event.action, 'payment.amount_changed'); assert.equal(event.entity.id, item.recurring_payment_id)
  assert.ok(event.changes.some(change => change.before === '45000.00 RUB' && change.after === '123.45 USD'))
  await request('/payment-occurrences/' + item.id + '/amount', 'PATCH', { amount: '123.45', currency: 'USD' })
  assert.equal((await audits()).total, priorAudit.total + 1)
  assert.equal((await occurrences()).find(row => row.id === item.id).amount_is_custom, true)
})

test('paid period edits reject even no-ops; unchanged default periods stay non-custom', async context => {
  const { request, occurrences, audits } = await fixture(context)
  const before = await occurrences(), paid = before.find(row => row.status === 'paid'), unpaid = before.find(row => row.status === 'unpaid')
  const audit = await audits()
  const noOp = await request('/payment-occurrences/' + unpaid.id + '/amount', 'PATCH', { amount: unpaid.amount, currency: unpaid.currency })
  assert.equal(noOp.status, 200); assert.equal((await noOp.json()).amount_is_custom, false)
  const ruleNoOp = await (await request('/recurring-payments/' + unpaid.recurring_payment_id, 'PATCH', { amount: unpaid.amount, currency: unpaid.currency })).json()
  assert.equal(ruleNoOp.payment.amount_effective_from, null)
  assert.equal(ruleNoOp.effective_from, '2026-11-01'); assert.equal(ruleNoOp.updated_periods, 0); assert.equal(ruleNoOp.preserved_custom_periods, 0)
  const rejected = await request('/payment-occurrences/' + paid.id + '/amount', 'PATCH', { amount: paid.amount, currency: paid.currency })
  assert.equal(rejected.status, 409); assert.equal((await rejected.json()).error.code, 'PAYMENT_ALREADY_PAID')
  assert.deepEqual(await occurrences(), before); assert.equal((await audits()).total, audit.total)
})

test('regular terms apply next month and preserve current, paid and custom snapshots atomically', async context => {
  const { request, occurrences, audits } = await fixture(context, { futurePeriods: true })
  const period = (await occurrences()).find(row => row.recurring_payment_id === FIGMA_ID && row.due_date === '2026-11-12')
  await request('/payment-occurrences/' + period.id + '/amount', 'PATCH', { amount: '77.77', currency: 'EUR' })
  const paidId = 'b0000000-2222-4222-8222-000000000001'
  await request('/payment-occurrences/' + paidId, 'PATCH', { status: 'paid', paid_on: '2026-10-23' })
  const before = await occurrences(), beforeAudit = await audits(), beforeSummary = await (await request('/payments/summary')).json()
  const response = await request('/recurring-payments/' + FIGMA_ID, 'PATCH', { amount: '20.50', currency: 'USD' })
  assert.equal(response.status, 200)
  const data = await response.json()
  assert.equal(data.effective_from, '2026-11-01'); assert.equal(data.updated_periods, 1); assert.equal(data.preserved_custom_periods, 1)
  assert.equal(data.payment.amount, '20.50'); assert.equal(data.payment.currency, 'USD'); assert.equal(data.payment.amount_effective_from, '2026-11-01')
  assert.equal(data.payment.anchor_day, 12); assert.equal(data.payment.first_due_date, '2026-08-12')
  const after = await occurrences(), changedId = 'b0000000-2222-4222-8222-000000000002'
  assert.deepEqual(after.filter(row => row.id !== changedId), before.filter(row => row.id !== changedId))
  const changed = after.find(row => row.id === changedId)
  assert.equal(changed.amount, '20.50'); assert.equal(changed.currency, 'USD'); assert.equal(changed.amount_is_custom, false)
  assert.deepEqual(await (await request('/payments/summary')).json(), beforeSummary)
  assert.equal((await audits()).total, beforeAudit.total + 1)
  const event = (await audits()).items[0]
  assert.equal(event.action, 'payment.terms_changed')
  assert.ok(event.changes.some(change => change.field === 'amount_effective_from' && change.after === '2026-11-01'))
  const noOp = await (await request('/recurring-payments/' + FIGMA_ID, 'PATCH', { amount: '20.50', currency: 'USD' })).json()
  assert.equal(noOp.updated_periods, 0); assert.equal(noOp.preserved_custom_periods, 0); assert.deepEqual(noOp.payment, data.payment)
  assert.equal((await audits()).total, beforeAudit.total + 1)
})

test('stopped unpaid periods remain editable while stopped recurring terms are rejected', async context => {
  const { request, occurrences, audits } = await fixture(context)
  const ruleId = (await occurrences()).find(row => row.due_date === '2026-10-20').recurring_payment_id
  assert.equal((await request('/recurring-payments/' + ruleId, 'DELETE')).status, 204)
  const audit = await audits()
  const ruleEdit = await request('/recurring-payments/' + ruleId, 'PATCH', { amount: '1.00', currency: 'EUR' })
  assert.equal(ruleEdit.status, 409); assert.equal((await ruleEdit.json()).error.code, 'RECURRING_PAYMENT_STOPPED')
  assert.equal((await audits()).total, audit.total)
  const stopped = (await occurrences()).find(row => row.recurring_payment_id === ruleId && row.status === 'unpaid')
  const periodEdit = await request('/payment-occurrences/' + stopped.id + '/amount', 'PATCH', { amount: '100.00', currency: 'EUR' })
  assert.equal(periodEdit.status, 200)
  const data = await periodEdit.json()
  assert.equal(data.recurring_payment_is_active, false); assert.equal(data.amount, '100.00')
})

test('editing enforces exact bodies, valid money, IDs, CSRF and admin role without mutating on failure', async context => {
  const { request, occurrences, audits, login } = await fixture(context)
  const before = await occurrences(), item = before.find(row => row.status === 'unpaid')
  const periodPath = '/payment-occurrences/' + item.id + '/amount', rulePath = '/recurring-payments/' + item.recurring_payment_id
  const audit = await audits()
  for (const path of [periodPath, rulePath]) {
    for (const body of [{ amount: 1, currency: 'USD' }, { amount: '0.00', currency: 'USD' }, { amount: '-1.00', currency: 'USD' }, { amount: '1000000000000.00', currency: 'USD' }, { amount: '1,00', currency: 'USD' }, { amount: '1.0', currency: 'USD' }, { amount: null, currency: 'USD' }, { amount: '1.00', currency: 'BTC' }, { amount: '1.00' }, { currency: 'USD' }, { amount: '1.00', currency: 'USD', status: 'paid' }]) assert.equal((await request(path, 'PATCH', body)).status, 422, JSON.stringify(body))
    assert.equal((await request(path + '?unexpected=1', 'PATCH', { amount: '1.00', currency: 'USD' })).status, 422)
    assert.equal((await request(path, 'PATCH', { amount: '1.00', currency: 'USD' }, 'invalid-csrf')).status, 403)
  }
  assert.equal((await request('/payment-occurrences/' + item.id, 'PATCH', { status: 'unpaid', paid_on: null, amount: '1.00' })).status, 422)
  assert.equal((await request('/payment-occurrences/not-a-uuid/amount', 'PATCH', { amount: '1.00', currency: 'USD' })).status, 422)
  assert.equal((await request('/payment-occurrences/00000000-0000-4000-8000-000000000000/amount', 'PATCH', { amount: '1.00', currency: 'USD' })).status, 404)
  assert.equal((await request('/recurring-payments/00000000-0000-4000-8000-000000000000', 'PATCH', { amount: '1.00', currency: 'USD' })).status, 404)
  assert.deepEqual(await occurrences(), before); assert.equal((await audits()).total, audit.total)
  await login('ivan', 'example-password-only')
  for (const path of [periodPath, rulePath]) assert.equal((await request(path, 'PATCH', { amount: '1.00', currency: 'USD' })).status, 403)
  assert.equal((await request('/payment-occurrences/' + item.id, 'PATCH', { status: 'unpaid', paid_on: null })).status, 200)
  assert.deepEqual(await occurrences(), before)
})

test('overdue amount and currency edits move overdue within unpaid without changing paid totals', async context => {
  const { request, occurrences } = await fixture(context)
  const item = (await occurrences()).find(row => row.due_date === '2026-10-20')
  const before = (await (await request('/payments/summary')).json()).totals
  const response = await request('/payment-occurrences/' + item.id + '/amount', 'PATCH', { amount: '99.99', currency: 'EUR' })
  assert.equal(response.status, 200)
  const updated = await response.json()
  assert.equal(updated.is_overdue, true); assert.equal(updated.days_late, 3)
  const after = (await (await request('/payments/summary')).json()).totals
  for (const field of ['planned', 'unpaid', 'overdue']) {
    assert.equal(cents(after.RUB[field]), cents(before.RUB[field]) - cents(item.amount))
    assert.equal(cents(after.EUR[field]), cents(before.EUR[field]) + 9999n)
  }
  for (const currency of ['RUB', 'USD', 'EUR']) assert.equal(after[currency].paid, before[currency].paid)
  assert.deepEqual(after.USD, before.USD)
})
