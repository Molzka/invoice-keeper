import assert from 'node:assert/strict'
import { Buffer } from 'node:buffer'
import { readFileSync } from 'node:fs'
import { stripTypeScriptTypes } from 'node:module'
import test from 'node:test'
import { URL } from 'node:url'

const source = stripTypeScriptTypes(readFileSync(new URL('./receipt-links.ts', import.meta.url), 'utf8'), { mode: 'transform' })
const { normalizeReceiptUrl, receiptHostname, receiptFileSize } = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'))

test('receipt links accept and normalize absolute HTTP(S) destinations', () => {
  assert.equal(normalizeReceiptUrl('  https://EXAMPLE.com/check?id=12#receipt  '), 'https://example.com/check?id=12#receipt')
  assert.equal(normalizeReceiptUrl('http://127.0.0.1:8000/receipts/12.pdf'), 'http://127.0.0.1:8000/receipts/12.pdf')
  assert.equal(normalizeReceiptUrl('https://example.com/check%20one.pdf'), 'https://example.com/check%20one.pdf')
  assert.equal(receiptHostname('https://EXAMPLE.com/check?signature=private'), 'example.com')
})

test('receipt links reject executable, relative, credential-bearing and malformed URLs', () => {
  for (const value of [
    '', ' ', null, 12, 'javascript:alert(1)', 'data:text/html,test', 'file:///etc/passwd',
    '//example.com/check', '/api/v1/receipt/12', 'example.com', 'mailto:user@example.com',
    'https://user:pass@example.com', 'https://user@example.com', 'https://:pass@example.com',
    'https://example.com/with space', 'https://exa\nmple.com', 'https:\\\\example.com',
    'https://example.com\\@evil.example', 'https://', 'https://[invalid]',
  ]) {
    assert.equal(normalizeReceiptUrl(value), null, String(value))
    assert.equal(receiptHostname(value), null, String(value))
  }
})

test('receipt file sizes show supplied sizes and reject missing or invalid data', () => {
  assert.equal(receiptFileSize(0), '0 Б')
  assert.equal(receiptFileSize(1023), '1023 Б')
  assert.equal(receiptFileSize(1024), '1 КБ')
  assert.equal(receiptFileSize(1536), '1,5 КБ')
  assert.equal(receiptFileSize(1024 * 1024), '1 МБ')
  for (const value of [undefined, -1, NaN, Infinity, 1.5, Number.MAX_SAFE_INTEGER + 1]) assert.equal(receiptFileSize(value), null)
})
