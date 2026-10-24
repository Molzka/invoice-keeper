/** Only absolute HTTP(S) links may reach an external browser destination. */
export function normalizeReceiptUrl(value: unknown): string | null {
  if (typeof value !== 'string') return null
  const input = value.trim()
  const unsafeCharacter = Array.from(input).some(character => character.charCodeAt(0) <= 32 || character.charCodeAt(0) === 127 || character === '\\')
  if (!/^https?:\/\//i.test(input) || unsafeCharacter) return null
  try {
    const url = new URL(input)
    if (!['http:', 'https:'].includes(url.protocol) || !url.hostname || url.username || url.password) return null
    return url.href
  } catch { return null }
}

export function receiptHostname(value: unknown): string | null {
  const safe = normalizeReceiptUrl(value)
  return safe ? new URL(safe).hostname : null
}

export function receiptFileSize(value: number | undefined): string | null {
  if (value === undefined || !Number.isSafeInteger(value) || value < 0) return null
  if (value < 1024) return `${value} Б`
  const units = ['КБ', 'МБ', 'ГБ', 'ТБ']
  let size = value / 1024, index = 0
  while (size >= 1024 && index < units.length - 1) { size /= 1024; index++ }
  return `${new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 }).format(size)} ${units[index]}`
}
