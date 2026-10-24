import assert from 'node:assert/strict'
import { Buffer } from 'node:buffer'
import { readFileSync } from 'node:fs'
import { stripTypeScriptTypes } from 'node:module'
import test from 'node:test'
import { URL } from 'node:url'
const source = stripTypeScriptTypes(readFileSync(new URL('./payment-calendar.ts', import.meta.url), 'utf8'), { mode: 'transform' })
const { calendarCells, calendarMonthDays, calendarMonthRange, validCalendarDay, moveCalendarMonth, readCalendarRoute, calendarHash, calendarOccurrenceFilters, loadCalendarOccurrences } = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'))
const today = '2026-10-23'
function occurrence(id, date = '2026-10-23') { return { id: String(id), title: 'Платёж ' + String(id), due_date: date } }

test('calendar uses Monday-first Gregorian weeks and actual month lengths', () => {
  const october = calendarCells('2026-10')
  assert.deepEqual(october.slice(0, 7), [null, null, null, '2026-10-01', '2026-10-02', '2026-10-03', '2026-10-04'])
  assert.equal(october.filter(Boolean).length, 31)
  assert.equal(october.length % 7, 0)
  assert.equal(calendarCells('0001-01')[0], '0001-01-01')
  assert.equal(calendarCells('2021-02').length, 28)
  assert.equal(calendarCells('2020-08').length, 42)
  assert.equal(calendarMonthDays('2000-02'), 29)
  assert.equal(calendarMonthDays('2100-02'), 28)
  assert.equal(calendarMonthDays('2028-02'), 29)
  assert.deepEqual(calendarMonthRange('2026-02'), { date_from: '2026-02-01', date_to: '2026-02-28' })
  assert.deepEqual(calendarMonthRange('2028-02'), { date_from: '2028-02-01', date_to: '2028-02-29' })
})

test('calendar month navigation respects year transitions and representable boundaries', () => {
  assert.equal(moveCalendarMonth('2026-12', 1), '2027-01')
  assert.equal(moveCalendarMonth('2027-01', -1), '2026-12')
  assert.equal(moveCalendarMonth('0001-01', -1), null)
  assert.equal(moveCalendarMonth('9999-12', 1), null)
  assert.equal(moveCalendarMonth('0099-12', 1), '0100-01')
  for (const bad of ['0000-01', '2026-00', '2026-13', '26-01', '2026-1', 'Infinity']) assert.throws(() => calendarMonthDays(bad), RangeError)
  assert.equal(validCalendarDay('2028-02-29'), true)
  assert.equal(validCalendarDay('2100-02-29'), false)
  assert.equal(validCalendarDay('2026-10-00'), false)
  assert.equal(validCalendarDay('2026-11-31'), false)
})

test('calendar URLs validate state, preserve filters and reject unknown status or dates', () => {
  const defaults = { month: '2026-10', day: today, currency: '', status: 'all' }
  assert.deepEqual(readCalendarRoute('#calendar', today), defaults)
  const selected = { month: '2028-02', day: '2028-02-29', currency: 'USD', status: 'overdue' }
  assert.deepEqual(readCalendarRoute(calendarHash(selected), today), selected)
  assert.deepEqual(calendarOccurrenceFilters(selected), { date_from: '2028-02-01', date_to: '2028-02-29', currency: 'USD', status: 'unpaid', is_overdue: true })
  assert.deepEqual(readCalendarRoute('#calendar?month=0000-01&day=2026-02-30&currency=BTC&status=stolen&limit=999999', today), { ...defaults, day: '2026-10-01' })
  assert.equal(readCalendarRoute('#calendar?month=2026-11&day=2026-10-23', today).day, '2026-11-01')
  assert.equal(readCalendarRoute('#calendar?month=2026-11', today).day, '2026-11-01')
  assert.equal(calendarOccurrenceFilters({ ...defaults, status: 'all' }).status, undefined)
  assert.deepEqual(calendarOccurrenceFilters({ ...defaults, status: 'paid' }), { date_from: '2026-10-01', date_to: '2026-10-31', status: 'paid' })
})

test('calendar loads every API page before publishing the month', async () => {
  const all = Array.from({ length: 217 }, (_, i) => occurrence(i))
  const calls = []
  const filters = { date_from: '2026-10-01', date_to: '2026-10-31', currency: 'USD' }
  const loaded = await loadCalendarOccurrences(filters, async query => {
    calls.push(query)
    return { items: all.slice(query.offset, query.offset + query.limit), total: all.length, limit: query.limit, offset: query.offset }
  })
  assert.equal(loaded.length, 217)
  assert.deepEqual(calls.map(item => item.offset), [0, 100, 200])
  assert.ok(calls.every(item => item.limit === 100 && item.currency === 'USD' && item.date_to === '2026-10-31'))
  assert.equal(new Set(loaded.map(item => item.id)).size, 217)
  assert.deepEqual(await loadCalendarOccurrences({}, async () => ({ items: [], total: 0, limit: 100, offset: 0 })), [])
})

test('calendar rejects failed, partial, duplicated and changing pages instead of showing empty dates', async () => {
  const first = Array.from({ length: 100 }, (_, i) => occurrence(i))
  await assert.rejects(loadCalendarOccurrences({}, async query => {
    if (query.offset) throw new Error('503 PERIODS_NOT_READY')
    return { items: first, total: 101, limit: 100, offset: 0 }
  }), /PERIODS_NOT_READY/)
  for (const tail of [
    { items: [], total: 101, limit: 100, offset: 100 },
    { items: [first[0]], total: 101, limit: 100, offset: 100 },
    { items: [occurrence(101)], total: 102, limit: 100, offset: 100 },
    { items: [occurrence(101)], total: 101, limit: 100, offset: 0 },
  ]) await assert.rejects(loadCalendarOccurrences({}, async query => query.offset ? tail : { items: first, total: 101, limit: 100, offset: 0 }))
  let active = true, requests = 0
  await assert.rejects(loadCalendarOccurrences({}, async () => { requests++; active = false; return { items: first, total: 101, limit: 100, offset: 0 } }, () => active), /отменена/)
  assert.equal(requests, 1)
})
