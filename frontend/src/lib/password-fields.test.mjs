import assert from 'node:assert/strict'
import { Buffer } from 'node:buffer'
import { readFileSync } from 'node:fs'
import { stripTypeScriptTypes } from 'node:module'
import test from 'node:test'
import { URL } from 'node:url'
const source = stripTypeScriptTypes(readFileSync(new URL('./password-fields.ts', import.meta.url), 'utf8'), { mode: 'transform' })
const { validatePasswordFields } = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'))

test('password validation preserves spaces and distinct Unicode forms exactly as typed', () => {
  for (const [current, next] of [[' password1 ', 'password1'], ['old', '        '], ['e\u0301password', 'épassword'], ['x', 'valid-password']]) {
    const values = { current_password: current, new_password: next, confirm_password: next }
    const before = { ...values }
    assert.deepEqual(validatePasswordFields(values), {})
    assert.deepEqual(values, before)
  }
})
test('password character limits match Python Unicode code points at every boundary', () => {
  const check = (current, next) => validatePasswordFields({ current_password: current, new_password: next, confirm_password: next })
  assert.deepEqual(check('x', '😀'.repeat(8)), {})
  assert.deepEqual(check('😀'.repeat(128), '🔑'.repeat(128)), {})
  assert.ok(check('', 'good-password').current_password)
  assert.ok(check('😀'.repeat(129), 'good-password').current_password)
  assert.ok(check('old', '😀'.repeat(7)).new_password)
  assert.ok(check('old', '😀'.repeat(129)).new_password)
})
test('unchanged passwords and mismatched or empty confirmations are rejected locally', () => {
  assert.ok(validatePasswordFields({ current_password: 'password1', new_password: 'password1', confirm_password: 'password1' }).new_password)
  assert.ok(validatePasswordFields({ current_password: 'old', new_password: ' password1 ', confirm_password: 'password1' }).confirm_password)
  assert.ok(validatePasswordFields({ current_password: 'old', new_password: 'password1', confirm_password: '' }).confirm_password)
})
