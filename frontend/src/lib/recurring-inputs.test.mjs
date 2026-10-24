import assert from 'node:assert/strict'
import { Buffer } from 'node:buffer'
import { readFileSync } from 'node:fs'
import { stripTypeScriptTypes } from 'node:module'
import test from 'node:test'
import { URL } from 'node:url'

const source = stripTypeScriptTypes(readFileSync(new URL('./recurring-inputs.ts', import.meta.url), 'utf8'), { mode: 'transform' })
const { normalizeRecurringAmount, isCalendarDate, previewMonthlyDueDates } = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'))

test('amount accepts whole units and either decimal separator as exact API strings', () => {
  for (const [input, expected] of [
    ['45000', '45000.00'], ['45000,50', '45000.50'], ['45000.50', '45000.50'],
    ['45000,5', '45000.50'], ['45000.5', '45000.50'], ['  45000,50\n', '45000.50'],
    ['00045000,05', '45000.05'], ['000000000000000000001', '1.00'],
    ['0,01', '0.01'], ['0000.01', '0.01'], ['999999999999.99', '999999999999.99'],
    ['999999999999,9', '999999999999.90'], ['123456789012.34', '123456789012.34'],
  ]) assert.equal(normalizeRecurringAmount(input), expected, input)
})

test('amount rejects zero, overflow, excess precision and unsupported number syntax', () => {
  for (const input of [
    '', ' ', '0', '0,0', '0.00', '000.00', '-1', '+1', '1e3', '1E3', '.50', ',50',
    '1.', '1,', '1.001', '1,001', '1,2.3', '1.2,3', '1..2', '1,,2', 'NaN', 'Infinity',
    '1000000000000', '1000000000000.00', '45 000', '45\u00a0000', '1\n2', '1_000',
    '１２', '١٢', '1, 50',
  ]) assert.equal(normalizeRecurringAmount(input), null, input)
})

test('monthly estimate includes first due date and restores the original day after a short month', () => {
  assert.deepEqual(previewMonthlyDueDates('2027-01-31'), ['2027-01-31', '2027-02-28', '2027-03-31'])
  assert.deepEqual(previewMonthlyDueDates('2027-01-30'), ['2027-01-30', '2027-02-28', '2027-03-30'])
  assert.deepEqual(previewMonthlyDueDates('2026-08-31'), ['2026-08-31', '2026-09-30', '2026-10-31'])
  assert.deepEqual(previewMonthlyDueDates('2027-02-28'), ['2027-02-28', '2027-03-28', '2027-04-28'])
})

test('monthly estimate handles leap years, centuries and year transitions without a Date object', () => {
  assert.deepEqual(previewMonthlyDueDates('2028-01-31'), ['2028-01-31', '2028-02-29', '2028-03-31'])
  assert.deepEqual(previewMonthlyDueDates('2100-01-31'), ['2100-01-31', '2100-02-28', '2100-03-31'])
  assert.deepEqual(previewMonthlyDueDates('2000-01-31'), ['2000-01-31', '2000-02-29', '2000-03-31'])
  assert.deepEqual(previewMonthlyDueDates('2026-12-31'), ['2026-12-31', '2027-01-31', '2027-02-28'])
  assert.deepEqual(previewMonthlyDueDates('0001-01-31'), ['0001-01-31', '0001-02-28', '0001-03-31'])
  assert.deepEqual(previewMonthlyDueDates('2020-01-31'), ['2020-01-31', '2020-02-29', '2020-03-31'])
})

test('invalid calendar values have no preview and dates stay in the supported year range', () => {
  for (const value of ['', '2027-02-29', '2100-02-29', '2026-04-31', '0000-01-01', '10000-01-01', '2026-00-10', '2026-13-10', '2026-01-00', '2026-1-01', ' 2026-01-01', '2026-10-23T00:00:00Z']) {
    assert.equal(isCalendarDate(value), false, value)
    assert.deepEqual(previewMonthlyDueDates(value), [], value)
  }
  assert.equal(isCalendarDate('2028-02-29'), true)
  assert.equal(isCalendarDate('0001-01-01'), true)
  assert.deepEqual(previewMonthlyDueDates('9999-11-30'), ['9999-11-30', '9999-12-30'])
  assert.deepEqual(previewMonthlyDueDates('9999-12-31'), ['9999-12-31'])
  for (const count of [0, -1, 1.5, NaN, Infinity]) assert.deepEqual(previewMonthlyDueDates('2027-01-31', count), [])
})
