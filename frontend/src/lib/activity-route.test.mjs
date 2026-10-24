import assert from 'node:assert/strict'
import { Buffer } from 'node:buffer'
import { readFileSync } from 'node:fs'
import { stripTypeScriptTypes } from 'node:module'
import test from 'node:test'
import { URL } from 'node:url'

const source = stripTypeScriptTypes(readFileSync(new URL('./activity-route.ts', import.meta.url), 'utf8'), { mode: 'transform' })
const { defaultActivityFilters, readActivityRoute, activityHash, activityDay, auditActionLabels } = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'))

test('activity deep links preserve applied filters, encoded search and pagination', () => {
  const defaults = defaultActivityFilters()
  assert.deepEqual(readActivityRoute('#activity'), defaults)
  for (const action of ['', ...Object.keys(auditActionLabels)]) {
    const filters = { date_from: '2024-02-29', date_to: '2026-10-31', actor: 'ivan', action, query: 'Сервер & офис / #1', limit: 24, offset: 48 }
    assert.deepEqual(readActivityRoute(activityHash(filters)), filters)
  }
  assert.equal(activityHash(defaults), '#activity?limit=12&offset=0')
})

test('invalid calendar ranges and unsupported URL values never reach the source', () => {
  for (const value of ['2023-02-29', '2100-02-29', '0000-01-01', '2026-13-01', 'garbage']) {
    const filters = readActivityRoute('#activity?date_from=' + value + '&date_to=2026-10-31')
    assert.equal(filters.date_from, '')
    assert.equal(filters.date_to, '')
  }
  assert.equal(readActivityRoute('#activity?date_from=2000-02-29').date_from, '2000-02-29')
  assert.equal(readActivityRoute('#activity?date_from=0001-01-01').date_from, '0001-01-01')
  assert.deepEqual(readActivityRoute('#activity?date_from=2026-10-31&date_to=2026-10-01'), defaultActivityFilters())
  const filters = readActivityRoute('#activity?action=system.secret&limit=100&offset=-2&token=secret&actor=%00ivan&q=hello%0Aworld')
  assert.equal(filters.action, '')
  assert.equal(filters.limit, 12)
  assert.equal(filters.offset, 0)
  assert.equal(filters.actor, 'ivan')
  assert.equal(filters.query, 'helloworld')
  assert.equal(activityHash(filters).includes('token'), false)
  assert.equal(readActivityRoute('#activity?offset=9007199254740992').offset, 0)
  assert.equal(readActivityRoute('#activity?offset=9999999').offset, 1000000)
})

test('activity groups technical timestamps by Moscow day across UTC midnight', () => {
  assert.equal(activityDay('2026-10-22T20:59:59Z'), '2026-10-22')
  assert.equal(activityDay('2026-10-22T21:00:00Z'), '2026-10-23')
  assert.equal(activityDay('2026-10-23T00:30:00+03:00'), '2026-10-23')
  assert.equal(activityDay('not-a-timestamp'), '')
})

test('audit day follows the authenticated timezone, including UTC midnight and daylight-saving boundaries', () => {
  const timestamp = '2026-10-22T21:00:00Z'
  assert.equal(activityDay(timestamp, 'Europe/Moscow'), '2026-10-23')
  assert.equal(activityDay(timestamp, 'UTC'), '2026-10-22')
  assert.equal(activityDay(timestamp, 'America/New_York'), '2026-10-22')
  assert.equal(activityDay('2026-11-01T03:59:59Z', 'America/New_York'), '2026-10-31')
  assert.equal(activityDay('2026-11-01T04:00:00Z', 'America/New_York'), '2026-11-01')
  assert.equal(activityDay('2026-10-23T00:30:00Z', 'Asia/Tokyo'), '2026-10-23')
})
