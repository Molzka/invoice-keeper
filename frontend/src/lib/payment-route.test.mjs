import assert from 'node:assert/strict'
import { Buffer } from 'node:buffer'
import { readFileSync } from 'node:fs'
import { stripTypeScriptTypes } from 'node:module'
import test from 'node:test'
import { URL } from 'node:url'

const source = stripTypeScriptTypes(readFileSync(new URL('./payment-route.ts', import.meta.url), 'utf8'), { mode: 'transform' })
const { defaultPaymentFilters, readPaymentRoute, paymentHash, viewHash } = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'))
const today = '2026-10-23'
const october = { date_from: '2026-10-01', date_to: '2026-10-31', currency: '', tab: 'all' }

test('workspace hashes have safe defaults and history keeps an unbounded range', () => {
  assert.deepEqual(readPaymentRoute('#payments', today), { view: 'payments', filters: october, limit: 6, offset: 0, ruleId: null })
  assert.deepEqual(readPaymentRoute('', today), readPaymentRoute('#payments', today))
  assert.equal(readPaymentRoute('#not-a-view', today).view, 'payments')
  assert.deepEqual(readPaymentRoute('#history', today).filters, { date_from: '', date_to: '', currency: '', tab: 'all' })
  assert.deepEqual(defaultPaymentFilters('payments', '2028-02-29'), { date_from: '2028-02-01', date_to: '2028-02-29', currency: '', tab: 'all' })
  assert.equal(defaultPaymentFilters('payments', '2100-02-01').date_to, '2100-02-28')
  assert.throws(() => defaultPaymentFilters('payments', '2027-02-29'), RangeError)
  for (const view of ['recurring', 'users']) {
    assert.equal(viewHash(view), `#${view}`)
    assert.deepEqual(readPaymentRoute(`#${view}?status=paid&limit=24&offset=48&recurring_payment_id=a`, today), { view, filters: october, limit: 6, offset: 0, ruleId: null })
  }
})

test('all status and currency deep links preserve filters and pagination on reload', () => {
  for (const tab of ['all', 'unpaid', 'overdue', 'paid']) {
    for (const currency of ['', 'RUB', 'USD', 'EUR']) {
      for (const limit of [6, 12, 24]) {
        const filters = { ...october, tab, currency }
        const hash = paymentHash('payments', filters, { limit, offset: limit * 2 })
        assert.deepEqual(readPaymentRoute(hash, today), { view: 'payments', filters, limit, offset: limit * 2, ruleId: null })
      }
    }
  }
  assert.equal(paymentHash('payments', { ...october, currency: 'USD', tab: 'paid' }), '#payments?date_from=2026-10-01&date_to=2026-10-31&currency=USD&status=paid&limit=6&offset=0')
})

test('history round trips empty and one-sided dates and encoded recurring IDs', () => {
  const blank = defaultPaymentFilters('history', today)
  const ruleId = 'Оплата / A&B? #1=USD+EUR'
  const hash = paymentHash('history', blank, { limit: 12, offset: 24, ruleId })
  assert.equal(hash.includes('date_from='), false)
  assert.equal(hash.includes('date_to='), false)
  assert.equal(hash.includes('Оплата'), false)
  assert.equal(readPaymentRoute('#history?recurring_payment_id=A?B', today).ruleId, 'A?B')
  assert.deepEqual(readPaymentRoute(hash, today), { view: 'history', filters: blank, limit: 12, offset: 24, ruleId })
  for (const dates of [{ date_from: '', date_to: '2028-02-29' }, { date_from: '2027-01-31', date_to: '' }]) {
    const filters = { ...blank, ...dates }
    assert.deepEqual(readPaymentRoute(paymentHash('history', filters), today).filters, filters)
  }
})

test('invalid or reversed calendar ranges cannot produce bad API queries', () => {
  for (const query of ['date_from=2026-02-29', 'date_to=2026-04-31', 'date_from=0000-01-01', 'date_from=2026-13-01', 'date_from=2026-01-00', 'date_from=2026-10-25&date_to=2026-10-01', 'date_from=2026-1-01', 'date_from=not-a-date', 'date_from=&date_to=']) {
    assert.deepEqual(readPaymentRoute('#payments?' + query, today).filters, october, query)
  }
  assert.deepEqual(readPaymentRoute('#payments?date_to=2026-11-01', today).filters, october)
  const leapRange = { date_from: '2028-02-29', date_to: '2028-03-31', currency: '', tab: 'all' }
  assert.deepEqual(readPaymentRoute(paymentHash('history', leapRange), today).filters, leapRange)
  assert.deepEqual(readPaymentRoute('#history?date_from=2028-02-30&date_to=2028-03-31', today).filters, defaultPaymentFilters('history', today))
  assert.deepEqual(readPaymentRoute('#history?date_from=2026-12-31&date_to=2026-01-01', today).filters, defaultPaymentFilters('history', today))
})

test('unknown query keys, enums, unsafe numbers and irrelevant rule IDs are discarded', () => {
  const parsed = readPaymentRoute('#payments?currency=BTC&status=late&limit=20&offset=-12&recurring_payment_id=secret&admin=true', today)
  assert.deepEqual(parsed, { view: 'payments', filters: october, limit: 6, offset: 0, ruleId: null })
  for (const value of ['1.5', '1e3', 'Infinity', 'NaN', '9007199254740992', 'abc']) {
    assert.equal(readPaymentRoute('#history?offset=' + value, today).offset, 0, value)
  }
  assert.equal(readPaymentRoute('#history?offset=1000001', today).offset, 1_000_000)
  assert.equal(readPaymentRoute('#history?offset=00012', today).offset, 12)
  assert.equal(readPaymentRoute('#history?limit=24&offset=48', today).limit, 24)
  assert.equal(readPaymentRoute('#history?limit=24&offset=48', today).offset, 48)
  assert.equal(readPaymentRoute('#history?recurring_payment_id=%00%0A%7Fabc%C2%80', today).ruleId, 'abc')
  assert.equal(readPaymentRoute('#history?recurring_payment_id=%20%20', today).ruleId, null)
  assert.equal(readPaymentRoute('#history?recurring_payment_id=' + 'x'.repeat(201), today).ruleId, null)
  assert.equal(paymentHash('payments', october, { ruleId: 'ignored' }).includes('recurring_payment_id'), false)
  assert.equal(paymentHash('history', october, { limit: 20, offset: -6 }), '#history?date_from=2026-10-01&date_to=2026-10-31&status=all&limit=6&offset=0')
})
