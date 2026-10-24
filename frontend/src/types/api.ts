export type Currency = 'RUB' | 'USD' | 'EUR'
export type Role = 'admin' | 'user'
export type CalendarDate = string
export type Money = string
export interface User { id: string; username: string; role: Role; created_at: string }
export interface LoginRequest { username: string; password: string }
export interface AuthResponse { user: User; csrf_token: string }
export interface PaginationParams { limit?: number; offset?: number }
export interface Page<T> { items: T[]; total: number; limit: number; offset: number }
export interface RecurringPayment {
  id: string; title: string; amount: Money; currency: Currency; first_due_date: CalendarDate
  next_due_date: CalendarDate | null; periodicity: 'monthly'; anchor_day: number
  is_active: boolean; created_at: string
}
export interface CreateRecurringPaymentRequest {
  title: string; amount: Money; currency: Currency; first_due_date: CalendarDate; periodicity: 'monthly'
}
export interface RecurringPaymentFilters extends PaginationParams { is_active?: boolean }
export interface PaymentOccurrence {
  id: string; recurring_payment_id: string; title: string; amount: Money; currency: Currency
  due_date: CalendarDate; status: 'unpaid' | 'paid'; paid_on: CalendarDate | null
  is_overdue: boolean; paid_late: boolean; days_late: number; recurring_payment_is_active: boolean
}
export interface OccurrenceFilters extends PaginationParams {
  date_from?: CalendarDate; date_to?: CalendarDate; status?: 'paid' | 'unpaid'; currency?: Currency
  recurring_payment_id?: string; is_overdue?: boolean
}
export type UpdateOccurrenceRequest = { status: 'paid'; paid_on: CalendarDate } | { status: 'unpaid'; paid_on: null }
export interface CurrencyTotals { planned: Money; paid: Money; unpaid: Money; overdue: Money }
export interface PaymentSummary {
  date_from: CalendarDate; date_to: CalendarDate; as_of_date: CalendarDate; timezone: 'Europe/Moscow'
  totals: Record<Currency, CurrencyTotals>
}
export interface SummaryParams { date_from?: CalendarDate; date_to?: CalendarDate }
export interface CreateUserRequest { username: string; password: string }
export interface UpdateUserRequest { username?: string; password?: string }
export interface ErrorDetail { field: string; code: string; message: string }
export interface ErrorResponse { error: { code: string; message: string; details: ErrorDetail[] } }

