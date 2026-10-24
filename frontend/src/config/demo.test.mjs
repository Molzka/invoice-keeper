import assert from 'node:assert/strict'
import { Buffer } from 'node:buffer'
import { readFileSync } from 'node:fs'
import { stripTypeScriptTypes } from 'node:module'
import test from 'node:test'
import { URL } from 'node:url'

// Node 24 is already required by this project. No browser or test dependency is needed.
const moduleUrls = new Map()
function sourceModuleUrl(file) {
  const key = file.href
  if (moduleUrls.has(key)) return moduleUrls.get(key)
  let source = stripTypeScriptTypes(readFileSync(file, 'utf8'), { mode: 'transform' })
  const imports = Array.from(source.matchAll(/\bfrom\s+(['"])(\.[^'"]+)\1/g), match => match[2])
  for (const dependency of new Set(imports)) {
    const dependencyUrl = sourceModuleUrl(new URL(dependency + '.ts', file))
    source = source.replaceAll("'" + dependency + "'", JSON.stringify(dependencyUrl)).replaceAll('"' + dependency + '"', JSON.stringify(dependencyUrl))
  }
  const result = 'data:text/javascript;base64,' + Buffer.from(source).toString('base64')
  moduleUrls.set(key, result)
  return result
}

test('demo UI defaults and mock creation share one clock independently of the host date', async () => {
  const NativeDate = globalThis.Date
  class LaterHostDate extends NativeDate {
    constructor(...args) { super(...(args.length ? args : ['2032-02-12T23:45:00Z'])) }
    static now() { return NativeDate.parse('2032-02-12T23:45:00Z') }
  }
  globalThis.Date = LaterHostDate
  const session = new Map()
  Object.defineProperty(globalThis, 'window', { configurable: true, value: { location: { origin: 'http://localhost', search: '' } } })
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: { getItem: key => session.get(key) ?? null, setItem: (key, value) => session.set(key, value), removeItem: key => session.delete(key) } })
  try {
    const clock = await import(sourceModuleUrl(new URL('./demo.ts', import.meta.url)))
    const fixtures = await import(sourceModuleUrl(new URL('../mocks/fixtures.ts', import.meta.url)))
    const { mockFetch } = await import(sourceModuleUrl(new URL('../mocks/transport.ts', import.meta.url)))
    assert.equal(clock.businessToday('mock'), '2026-10-23')
    assert.equal(clock.businessNowIso('mock'), '2026-10-23T09:30:00.000Z')
    assert.equal(clock.DEMO_DATE_LABEL, '23 октября 2026')
    assert.equal(clock.businessToday('real', new NativeDate('2026-10-23T22:30:00Z')), '2026-10-24')
    assert.equal(clock.businessToday('real'), '2032-02-13')
    assert.equal(clock.businessNowIso('real'), '2032-02-12T23:45:00.000Z')
    assert.equal(clock.calendarMonthDate('2027-01-31', 31, 1), '2027-02-28')
    assert.equal(clock.calendarMonthDate('2028-01-31', 31, 1), '2028-02-29')
    const seed = fixtures.createFixtures()
    assert.ok(seed.users.every(user => user.created_at.slice(0, 10) <= clock.DEMO_TODAY))
    assert.ok(seed.recurring.every(rule => rule.created_at.slice(0, 10) <= clock.DEMO_TODAY))
    assert.ok(seed.occurrences.every(item => !item.paid_on || item.paid_on <= clock.DEMO_TODAY))
    assert.ok(seed.recurring.every(rule => rule.is_active ? rule.next_due_date >= clock.DEMO_TODAY : rule.next_due_date === null))
    let csrf = ''
    async function send(path, method = 'GET', body) {
      const response = await mockFetch('/api/v1' + path, { method, headers: { ...(body ? { 'Content-Type': 'application/json' } : {}), ...(csrf ? { 'X-CSRF-Token': csrf } : {}) }, ...(body ? { body: JSON.stringify(body) } : {}) })
      return { status: response.status, data: await response.json() }
    }
    const auth = await send('/auth/login', 'POST', { username: 'admin', password: 'Admin123!' })
    assert.equal(auth.status, 200)
    csrf = auth.data.csrf_token
    const createRule = first_due_date => send('/recurring-payments', 'POST', { title: 'Clock regression', amount: '1.00', currency: 'RUB', first_due_date, periodicity: 'monthly' })
    const current = await createRule(clock.businessToday('mock'))
    assert.equal(current.status, 201)
    assert.equal(current.data.created_at, clock.DEMO_NOW_ISO)
    assert.equal(current.data.next_due_date, clock.DEMO_TODAY)
    const currentPeriods = await send('/payment-occurrences?recurring_payment_id=' + current.data.id)
    assert.equal(currentPeriods.data.total, 1)
    assert.equal(currentPeriods.data.items[0].due_date, clock.DEMO_TODAY)
    assert.equal(currentPeriods.data.items[0].is_overdue, false)
    const futureDue = clock.calendarMonthDate(clock.DEMO_TODAY, 23, 1)
    const future = await createRule(futureDue)
    assert.equal(future.status, 201)
    assert.equal(future.data.created_at, clock.DEMO_NOW_ISO)
    assert.equal(future.data.next_due_date, futureDue)
    const futurePeriods = await send('/payment-occurrences?recurring_payment_id=' + future.data.id)
    assert.equal(futurePeriods.data.total, 1)
    assert.equal(futurePeriods.data.items[0].due_date, futureDue)
    const user = await send('/users', 'POST', { username: 'clock-test', password: 'password123' })
    assert.equal(user.data.created_at, clock.DEMO_NOW_ISO)
    const summary = await send('/payments/summary')
    assert.equal(summary.data.as_of_date, clock.DEMO_TODAY)
    assert.deepEqual({ date_from: summary.data.date_from, date_to: summary.data.date_to }, clock.calendarMonthBounds(clock.DEMO_TODAY))
    const futurePayment = await send('/payment-occurrences/' + currentPeriods.data.items[0].id, 'PATCH', { status: 'paid', paid_on: '2026-10-24' })
    assert.equal(futurePayment.status, 422)
  } finally { globalThis.Date = NativeDate }
})
