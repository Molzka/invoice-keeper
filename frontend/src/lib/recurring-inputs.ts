import type { Periodicity } from '../types/api'

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

/** Compatibility helper for callers that only need the monthly default. */
export function previewMonthlyDueDates(firstDueDate: string, count = 3): string[] {
  return previewRecurringDueDates(firstDueDate, 'monthly', 1, count);
}

export function* recurringDueDates(firstDueDate: string, periodicity: Periodicity, interval = 1, start = firstDueDate): Generator<string> {
  if (!isCalendarDate(firstDueDate) || !isCalendarDate(start) || !Number.isInteger(interval) || interval < 1 || interval > 365) return;
  if (periodicity === 'once') { if (firstDueDate >= start) yield firstDueDate; return; }
  const [year, month, anchorDay] = firstDueDate.split('-').map(Number);
  const firstMonth = (year - 1) * 12 + month - 1;
  const [startYear, startMonth] = start.split('-').map(Number);
  const byDays = periodicity === 'daily' || periodicity === 'weekly';
  const step = interval * (periodicity === 'weekly' ? 7 : periodicity === 'yearly' ? 12 : 1);
  const firstTime = Date.parse(firstDueDate + 'T00:00:00Z');
  const elapsed = byDays ? (Date.parse(start + 'T00:00:00Z') - firstTime) / 86400000 : (startYear - year) * 12 + startMonth - month;
  for (let index = Math.max(0, Math.floor(elapsed / step)); ; index++) {
    let due: string;
    if (byDays) {
      const time = firstTime + index * step * 86400000;
      if (time > Date.parse('9999-12-31T00:00:00Z')) return;
      due = new Date(time).toISOString().slice(0, 10);
    } else {
      const targetMonth = firstMonth + index * step;
      if (targetMonth >= 9999 * 12) return;
      const targetYear = Math.floor(targetMonth / 12) + 1;
      const monthOfYear = targetMonth % 12 + 1;
      const day = Math.min(anchorDay, daysInMonth(targetYear, monthOfYear));
      due = `${String(targetYear).padStart(4, '0')}-${String(monthOfYear).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
    }
    if (due >= start) yield due;
  }
}

export function previewRecurringDueDates(firstDueDate: string, periodicity: Periodicity, interval = 1, count = 3): string[] {
  if (!Number.isInteger(count) || count < 1) return [];
  const dates: string[] = [];
  for (const due of recurringDueDates(firstDueDate, periodicity, interval)) {
    dates.push(due);
    if (dates.length === count) break;
  }
  return dates;
}

export function recurrenceLabel(periodicity: Periodicity, interval = 1): string {
  if (periodicity === 'once') return 'Один раз';
  const units = { daily: ['день', 'дня', 'дней'], weekly: ['неделю', 'недели', 'недель'], monthly: ['месяц', 'месяца', 'месяцев'], yearly: ['год', 'года', 'лет'] };
  const plural = new Intl.PluralRules('ru').select(interval);
  return `Раз в ${interval} ${units[periodicity][plural === 'one' ? 0 : plural === 'few' ? 1 : 2]}`;
}
