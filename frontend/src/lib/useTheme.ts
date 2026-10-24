import { useSyncExternalStore } from 'react'
import { resolveTheme, themePreference, themeStorageKey } from './theme'
import type { ThemePreference } from './theme'
const themeEvent = 'invoice:themechange'
const systemTheme = window.matchMedia('(prefers-color-scheme: dark)')
function storedTheme(): ThemePreference {
  try { return themePreference(window.localStorage.getItem(themeStorageKey)) } catch { return 'system' }
}
let preference = storedTheme()
function applyTheme() {
  const resolved = resolveTheme(preference, systemTheme.matches)
  document.documentElement.dataset.theme = resolved
  document.documentElement.style.colorScheme = resolved
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', resolved === 'dark' ? '#000000' : '#f4f4f4')
}
applyTheme()
function snapshot() { return preference + ':' + resolveTheme(preference, systemTheme.matches) }
function subscribe(onChange: () => void) {
  function systemChanged() { if (preference === 'system') { applyTheme(); onChange() } }
  function storageChanged(event: StorageEvent) {
    if (event.key !== null && event.key !== themeStorageKey) return
    preference = themePreference(event.newValue)
    applyTheme(); onChange()
  }
  window.addEventListener(themeEvent, onChange)
  window.addEventListener('storage', storageChanged)
  systemTheme.addEventListener('change', systemChanged)
  return () => {
    window.removeEventListener(themeEvent, onChange)
    window.removeEventListener('storage', storageChanged)
    systemTheme.removeEventListener('change', systemChanged)
  }
}
export function setThemePreference(value: ThemePreference) {
  preference = themePreference(value)
  try { window.localStorage.setItem(themeStorageKey, preference) } catch { /* Keep this tab usable when storage is restricted. */ }
  applyTheme()
  window.dispatchEvent(new Event(themeEvent))
}
export function useTheme() {
  const value = useSyncExternalStore(subscribe, snapshot)
  const [preference, resolved] = value.split(':')
  return { preference: themePreference(preference), resolved: resolved as 'light' | 'dark', setPreference: setThemePreference }
}
