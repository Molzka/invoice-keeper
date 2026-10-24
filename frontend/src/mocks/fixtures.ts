import type { PaymentOccurrence, RecurringPayment, User } from '../types/api'

import { calendarMonthDate, DEMO_TODAY, shiftCalendarDays } from '../config/demo'
export { DEMO_TODAY } from '../config/demo'
export const ADMIN_ID = '37f7b8e8-ff0e-4a9d-a1d2-6391238b5947'
export const IVAN_ID = '9b3a2a64-c7a9-4dd0-98f4-e5e1458ad1d6'
export const RENT_ID = 'f059226b-8948-4da4-b33e-3b22844b4587'
export const demoUsers: User[] = [
  { id: ADMIN_ID, username: 'admin', role: 'admin', created_at: `${calendarMonthDate(DEMO_TODAY, 1)}T09:00:00Z` },
  { id: IVAN_ID, username: 'ivan', role: 'user', created_at: `${DEMO_TODAY}T09:00:00Z` },
  { id: 'b6000000-1111-4111-8111-000000000001', username: 'anna', role: 'user', created_at: `${calendarMonthDate(DEMO_TODAY, 12)}T10:15:00Z` },
]
const rules: [string, string, string, RecurringPayment['currency'], number, boolean][] = [
  [RENT_ID, 'Аренда офиса', '45000.00', 'RUB', 31, true],
  ['f0000000-1111-4111-8111-000000000002', 'Облачный сервер · production', '25.00', 'USD', 25, true],
  ['f0000000-1111-4111-8111-000000000003', 'Figma · рабочее пространство', '9.00', 'EUR', 12, true],
  ['f0000000-1111-4111-8111-000000000004', 'Интернет в офисе', '5000.00', 'RUB', 20, true],
  ['f0000000-1111-4111-8111-000000000005', 'Обслуживание оборудования', '10000.00', 'RUB', 28, true],
  ['f0000000-1111-4111-8111-000000000006', 'Домен invoicekeeper.app', '12.00', 'USD', 18, true],
  ['f0000000-1111-4111-8111-000000000007', 'Notion · база знаний', '18.00', 'EUR', 23, true],
  ['f0000000-1111-4111-8111-000000000008', 'Резервное копирование', '3200.00', 'RUB', 24, true],
  ['f0000000-1111-4111-8111-000000000009', 'Лицензия на систему мониторинга инфраструктуры и уведомлений для распределённой команды разработки', '149.00', 'USD', 29, true],
  ['f0000000-1111-4111-8111-000000000010', 'Старый VPS · архив', '15.00', 'EUR', 5, false],
  ['f0000000-1111-4111-8111-000000000011', 'Бухгалтерское сопровождение', '18000.00', 'RUB', 15, true],
  ['f0000000-1111-4111-8111-000000000012', 'Почта команды', '8.00', 'USD', 26, true],
]
export function createFixtures(stress = false): { users: User[]; recurring: RecurringPayment[]; occurrences: PaymentOccurrence[] } {
  const recurring = rules.map(([id, title, amount, currency, day, active], index): RecurringPayment => ({
    id, title: stress && index === 8 ? title.repeat(2).slice(0, 200) : title,
    amount: stress && index === 8 ? '999999999999.99' : amount, currency,
    first_due_date: calendarMonthDate(DEMO_TODAY, day, -2), next_due_date: active ? calendarMonthDate(DEMO_TODAY, day, calendarMonthDate(DEMO_TODAY, day) < DEMO_TODAY ? 1 : 0) : null,
    periodicity: 'monthly', anchor_day: day, is_active: active, amount_effective_from: null,
    created_at: `${calendarMonthDate(DEMO_TODAY, index + 1, -2)}T09:30:00Z`,
  }))
  const occurrences: PaymentOccurrence[] = []
  recurring.forEach((rule, index) => {
    const needsFuture = rule.is_active && calendarMonthDate(DEMO_TODAY, rule.anchor_day) < DEMO_TODAY
    for (const monthOffset of [-2, -1, 0, ...(needsFuture ? [1] : [])]) {
      const due_date = calendarMonthDate(DEMO_TODAY, rule.anchor_day, monthOffset)
      const month = Number(due_date.slice(5, 7))
      const paid = monthOffset < 0 || (monthOffset === 0 && due_date <= DEMO_TODAY && [2, 5, 6, 9, 10].includes(index))
      const paid_on = paid ? (monthOffset === 0 && index === 5 ? shiftCalendarDays(DEMO_TODAY, -2) : due_date) : null
      occurrences.push({ id: monthOffset === 0 && index === 0 ? '349e2b3b-1683-490a-a0ac-608cefc30248' : `a${String(month).padStart(7, '0')}-1111-4111-8111-${String(index + 1).padStart(12, '0')}`, recurring_payment_id: rule.id,
        title: rule.title, amount: rule.amount, currency: rule.currency, due_date, status: paid ? 'paid' : 'unpaid', paid_on,
        is_overdue: !paid && due_date < DEMO_TODAY, paid_late: Boolean(paid_on && paid_on > due_date), days_late: 0,
        recurring_payment_is_active: rule.is_active, amount_is_custom: false,
      })
    }
  })
  return { users: structuredClone(demoUsers), recurring, occurrences }
}

