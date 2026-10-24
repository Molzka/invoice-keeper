import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { stripTypeScriptTypes } from 'node:module'
import { Buffer } from 'node:buffer'
import { URL } from 'node:url'
import { runInNewContext } from 'node:vm'
import test from 'node:test'
const source = stripTypeScriptTypes(readFileSync(new URL('./theme.ts', import.meta.url), 'utf8'), { mode: 'transform' })
const { themePreference, resolveTheme } = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'))
const boot = readFileSync(new URL('../../public/theme-init.js', import.meta.url), 'utf8')
function startup(saved, dark, blocked = false, mediaAvailable = true) {
  const attributes = {}
  const style = {}
  runInNewContext(boot, {
    localStorage: { getItem() { if (blocked) throw new Error('Storage blocked'); return saved } },
    window: mediaAvailable ? { matchMedia: () => ({ matches: dark }) } : {},
    document: { documentElement: { style, setAttribute: (key, value) => { attributes[key] = value } } },
  })
  return { theme: attributes['data-theme'], colorScheme: style.colorScheme }
}
test('theme preferences accept known manual values and use the system for missing or invalid storage', () => {
  assert.equal(themePreference('light'), 'light')
  assert.equal(themePreference('dark'), 'dark')
  for (const value of ['system', '', null, undefined, 'invalid', 1]) assert.equal(themePreference(value), 'system')
})
test('explicit choice wins over the operating system and system choice follows it', () => {
  assert.equal(resolveTheme('light', true), 'light')
  assert.equal(resolveTheme('dark', false), 'dark')
  assert.equal(resolveTheme('system', true), 'dark')
  assert.equal(resolveTheme('system', false), 'light')
})
test('early initialization restores the correct palette before React and agrees with the theme resolver', () => {
  for (const saved of ['light', 'dark', 'system', 'invalid', null]) for (const dark of [true, false]) {
    const expected = resolveTheme(themePreference(saved), dark)
    assert.deepEqual(startup(saved, dark), { theme: expected, colorScheme: expected })
  }
})
test('theme startup stays usable with blocked storage or unavailable system media preference', () => {
  assert.deepEqual(startup('light', true, true), { theme: 'dark', colorScheme: 'dark' })
  assert.deepEqual(startup(null, false, false, false), { theme: 'light', colorScheme: 'light' })
})
