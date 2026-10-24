/** Return the API decimal representation without using floating point money. */
export function normalizeRecurringAmount(value: string): string | null {
  const trimmed = value.trim();
  if (!/^\d+(?:[.,]\d{1,2})?$/.test(trimmed)) return null;
  const [rawWhole, rawFraction = ''] = trimmed.split(/[.,]/);
  const whole = rawWhole.replace(/^0+(?=\d)/, '');
  const fraction = rawFraction.padEnd(2, '0');
  if (whole.length > 12 || (whole === '0' && fraction === '00')) return null;
  return `${whole}.${fraction}`;
}

function daysInMonth(year: number, month: number) {
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  return [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1];
}

export function isCalendarDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const [year, month, day] = value.split('-').map(Number);
  return year >= 1 && month >= 1 && month <= 12 && day >= 1 && day <= daysInMonth(year, month);
}

/** Calendar-only estimate; every month retains the original day as its anchor. */
export function previewMonthlyDueDates(firstDueDate: string, count = 3): string[] {
  if (!isCalendarDate(firstDueDate) || !Number.isInteger(count) || count < 1) return [];
  const [year, month, anchorDay] = firstDueDate.split('-').map(Number);
  const firstMonth = (year - 1) * 12 + month - 1;
  const dates: string[] = [];
  // Never create a five-digit year outside the API's YYYY-MM-DD range.
  const lastMonth = Math.min(firstMonth + count - 1, 9999 * 12 - 1);
  for (let targetMonth = firstMonth; targetMonth <= lastMonth; targetMonth++) {
    const targetYear = Math.floor(targetMonth / 12) + 1;
    const monthOfYear = targetMonth % 12 + 1;
    const day = Math.min(anchorDay, daysInMonth(targetYear, monthOfYear));
    dates.push(`${String(targetYear).padStart(4, '0')}-${String(monthOfYear).padStart(2, '0')}-${String(day).padStart(2, '0')}`);
  }
  return dates;
}
