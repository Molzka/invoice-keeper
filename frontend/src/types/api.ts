export type Currency = 'RUB' | 'USD' | 'EUR'
export type Role = 'admin' | 'user'
export type CalendarDate = string
export type Money = string
export interface User { id: string; username: string; role: Role; created_at: string }
export interface LoginRequest { username: string; password: string }
export interface ChangePasswordRequest { current_password: string; new_password: string }
export interface AuthResponse { user: User; csrf_token: string; timezone: string }
export type MfaMethod = 'totp' | 'telegram' | 'recovery'
export type MfaFactor = Exclude<MfaMethod, 'recovery'>
export interface MfaChallenge { mfa_required: true; methods: MfaMethod[]; csrf_token: string; expires_at: string }
export type LoginResponse = AuthResponse | MfaChallenge
export interface TelegramAccount { id: string; username: string | null; display_name: string }
export interface SecurityState { can_manage: boolean; mfa_enabled: boolean; methods: MfaFactor[]; available_methods: MfaFactor[]; telegram: TelegramAccount | null; recovery_codes_remaining: number }
export interface SecurityMutation { security: SecurityState; recovery_codes?: string[] }
export interface TotpSetup { setup_id: string; secret: string; otpauth_uri: string; expires_at: string }
export interface TelegramSetup { setup_id: string; link: string; expires_at: string }
export interface TelegramSetupStatus { status: 'waiting' | 'claimed'; account: TelegramAccount | null; expires_at: string }
export interface ReauthRequest { password: string; method?: MfaMethod; code?: string }
export type RegistrationStatus = 'pending' | 'approved' | 'rejected'
export interface RegistrationRequest { id: string; username: string; message: string; status: RegistrationStatus; created_at: string; reviewed_at: string | null; reviewed_by: string | null; decision_note: string | null }
export type RegistrationRequestList = Page<RegistrationRequest>
export interface RegistrationPayload { username: string; password: string; password_confirm: string; message: string; altcha: string }
export interface PaginationParams { limit?: number; offset?: number }
export interface Page<T> { items: T[]; total: number; limit: number; offset: number }
export interface RecurringPayment {
  id: string; title: string; amount: Money; currency: Currency; first_due_date: CalendarDate
  next_due_date: CalendarDate | null; periodicity: 'monthly' | 'once'; is_archived?: boolean; anchor_day: number
  is_active: boolean; created_at: string; amount_effective_from: CalendarDate | null
}
export interface CreateRecurringPaymentRequest {
  title: string; amount: Money; currency: Currency; first_due_date: CalendarDate; periodicity: 'monthly'
}
export interface RecurringPaymentFilters extends PaginationParams { is_active?: boolean; periodicity?: 'monthly' | 'once'; include_archived?: boolean }
export interface PaymentOccurrence {
  id: string; recurring_payment_id: string; title: string; amount: Money; currency: Currency
  due_date: CalendarDate; status: 'unpaid' | 'paid'; paid_on: CalendarDate | null
  periodicity?: 'monthly' | 'once'; is_cancelled?: boolean; is_overdue: boolean; paid_late: boolean; days_late: number; recurring_payment_is_active: boolean; amount_is_custom: boolean
}
export interface OccurrenceFilters extends PaginationParams {
  date_from?: CalendarDate; date_to?: CalendarDate; status?: 'paid' | 'unpaid'; currency?: Currency
  recurring_payment_id?: string; is_overdue?: boolean; include_cancelled?: boolean
}
export interface AmountCurrencyUpdateRequest { amount: Money; currency: Currency }
export interface RecurringAmountUpdateResponse { payment: RecurringPayment; effective_from: CalendarDate; updated_periods: number; preserved_custom_periods: number }
export type UpdateOccurrenceRequest = { status: 'paid'; paid_on: CalendarDate } | { status: 'unpaid'; paid_on: null }
export interface CurrencyTotals { planned: Money; paid: Money; unpaid: Money; overdue: Money }
export interface PaymentSummary {
  date_from: CalendarDate; date_to: CalendarDate; as_of_date: CalendarDate; timezone: string
  totals: Record<Currency, CurrencyTotals>
}
export interface SummaryParams { date_from?: CalendarDate; date_to?: CalendarDate }
export interface CreateUserRequest { username: string; password: string }
export interface UpdateUserRequest { username?: string; password?: string }
export interface ErrorDetail { field: string; code: string; message: string }
export interface ErrorResponse { error: { code: string; message: string; details: ErrorDetail[] } }

