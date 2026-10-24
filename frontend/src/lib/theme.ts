export type ThemePreference = 'light' | 'dark' | 'system'
export type ResolvedTheme = 'light' | 'dark'
export const themeStorageKey = 'invoice-keeper:theme'
export function themePreference(value: unknown): ThemePreference {
  return value === 'light' || value === 'dark' ? value : 'system'
}
export function resolveTheme(preference: ThemePreference, systemDark: boolean): ResolvedTheme {
  return preference === 'system' ? systemDark ? 'dark' : 'light' : preference
}
