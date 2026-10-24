import type { AuditFilters, AuditPage } from '../types/activity'
import type {
  AuthResponse, ChangePasswordRequest, CreateRecurringPaymentRequest, CreateUserRequest, ErrorResponse,
  LoginRequest, OccurrenceFilters, Page, PaginationParams, PaymentOccurrence, PaymentSummary,
  RecurringPayment, RecurringPaymentFilters, SummaryParams, UpdateOccurrenceRequest, UpdateUserRequest, User,
} from '../types/api'
import { mockFetch } from '../mocks/transport'

import { ApiError } from './errors'
export { ApiError, isMissingPaymentRoute } from './errors'
export type { ApiRequestContext } from './errors'

export const API_MODE = import.meta.env.VITE_API_MODE === 'real' ? 'real' : 'mock'
const BASE_URL = (import.meta.env.VITE_API_BASE_URL || '/api/v1').replace(/\/$/, '')
const REQUEST_TIMEOUT_MS = 12000
let csrfToken: string | null = null
let sessionUser: AuthResponse['user'] | null = null
function installSession(data: AuthResponse) { csrfToken = data.csrf_token; sessionUser = data.user }
function clearSession(message?: string) {
  csrfToken = null; sessionUser = null
  window.dispatchEvent(new CustomEvent('invoice:unauthorized', { detail: { message } }))
}
const transport = API_MODE === 'real' ? (url: string, init: RequestInit) => fetch(url, init) : mockFetch
function query(params?: object): string {
  const search = new URLSearchParams()
  Object.entries(params || {}).forEach(([key, value]) => { if (value !== undefined && value !== null && value !== '') search.set(key, String(value)) })
  return search.size ? '?' + search.toString() : ''
}
/** This API uses delta-seconds, not dates. Ignore malformed values and bound UI timers. */
function retryAfterSeconds(response: Response): number | undefined {
  const value = response.headers.get('Retry-After')
  if (value === null || !/^\d+$/.test(value)) return undefined
  return Math.min(Number(value), 86400)
}
async function request<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const requestContext = { method: method.toUpperCase(), path: path.split(/[?#]/, 1)[0] }
  const expectedUser = sessionUser
  const headers = new Headers({ Accept: 'application/json' })
  if (body !== undefined) headers.set('Content-Type', 'application/json')
  if (['POST', 'PATCH', 'DELETE'].includes(method) && path !== '/auth/login' && csrfToken) headers.set('X-CSRF-Token', csrfToken)
  const abort = new AbortController()
  const timeout = setTimeout(() => abort.abort(), REQUEST_TIMEOUT_MS)
  try {
    // Exactly one attempt. Creating POSTs cannot be safely replayed after an unknown outcome.
    const response = await transport(BASE_URL + path, { method, headers, credentials: 'include', signal: abort.signal,
      ...(body === undefined ? {} : { body: JSON.stringify(body) }), cache: 'no-store' })
    if (response.status === 204) return undefined as T
    let payload: unknown
    try { payload = await response.json() } catch (error) {
      if (response.status === 401) clearSession()
      // A disconnected or timed-out response body still has an unknown mutation outcome.
      if (abort.signal.aborted || error instanceof TypeError) throw error
      throw new ApiError(response.status, 'INVALID_RESPONSE', 'Сервер вернул ответ в неизвестном формате', [], requestContext, retryAfterSeconds(response))
    }
    if (!response.ok) {
      const serverError = (payload as Partial<ErrorResponse>)?.error
      const error = new ApiError(response.status, serverError?.code || 'HTTP_ERROR', serverError?.message || 'Не удалось выполнить запрос', Array.isArray(serverError?.details) ? serverError.details : [], requestContext, retryAfterSeconds(response))
      if (response.status === 401 && !(path === '/auth/login' && error.code === 'INVALID_CREDENTIALS')) {
        clearSession()
      }
      if (response.status === 403 && error.code === 'CSRF_FAILED' && expectedUser && ['POST', 'PATCH', 'DELETE'].includes(method)) {
        await recoverCsrfSession(expectedUser, requestContext)
        throw new ApiError(403, 'CSRF_RECOVERED', 'Сессия обновлена. Действие не выполнено — повторите его вручную.', [], requestContext)
      }
      throw error
    }
    return payload as T
  } catch (error) {
    if (error instanceof ApiError) throw error
    if (abort.signal.aborted) throw new ApiError(0, 'TIMEOUT', 'Сервер не ответил вовремя. Перед повторным созданием проверьте список: запись могла сохраниться.', [], requestContext)
    throw new ApiError(0, 'NETWORK_ERROR', 'Нет связи с сервером. Проверьте подключение и попробуйте ещё раз.', [], requestContext)
  } finally { clearTimeout(timeout) }
}

async function recoverCsrfSession(expectedUser: AuthResponse['user'], context: { method: string; path: string }): Promise<void> {
  let data: AuthResponse
  try { data = await request<AuthResponse>('/auth/me') }
  catch (error) {
    if (error instanceof ApiError && error.status === 401) throw error
    throw new ApiError(403, 'CSRF_REFRESH_FAILED', 'Действие не выполнено. Не удалось обновить сессию — проверьте соединение и обновите страницу.', [], context)
  }
  if (!data?.user || typeof data.csrf_token !== 'string' || !data.csrf_token) {
    throw new ApiError(403, 'CSRF_REFRESH_FAILED', 'Действие не выполнено. Сервер не подтвердил сессию — обновите страницу.', [], context)
  }
  // A shared cookie can now belong to another account. Do not authorize an old form with its token.
  if (!sessionUser || sessionUser.id !== expectedUser.id || sessionUser.role !== expectedUser.role || data.user.id !== expectedUser.id || data.user.role !== expectedUser.role) {
    const message = 'Аккаунт или права доступа изменились в другой вкладке. Войдите снова.'
    clearSession(message)
    throw new ApiError(401, 'AUTH_REQUIRED', message, [], context)
  }
  installSession(data)
}

export const api = {
  listAuditEvents: (filters: AuditFilters): Promise<AuditPage> => {
    if (API_MODE !== 'mock') return Promise.reject(new ApiError(501, 'AUDIT_NOT_AVAILABLE', 'Журнал действий ещё не подключён к серверу'))
    return request<AuditPage>('/audit-events' + query(filters))
  },
  async login(payload: LoginRequest): Promise<AuthResponse> { const data = await request<AuthResponse>('/auth/login', 'POST', payload); installSession(data); return data },
  async changePassword(payload: ChangePasswordRequest): Promise<AuthResponse> { const data = await request<AuthResponse>('/auth/change-password', 'POST', { current_password: payload.current_password, new_password: payload.new_password }); installSession(data); return data },
  async me(): Promise<AuthResponse> { const data = await request<AuthResponse>('/auth/me'); installSession(data); return data },
  async logout(): Promise<void> { await request<void>('/auth/logout', 'POST'); csrfToken = null; sessionUser = null },
  listOccurrences: (filters: OccurrenceFilters = {}) => request<Page<PaymentOccurrence>>('/payment-occurrences' + query(filters)),
  getOccurrence: (id: string) => request<PaymentOccurrence>('/payment-occurrences/' + encodeURIComponent(id)),
  updateOccurrence: (id: string, payload: UpdateOccurrenceRequest) => request<PaymentOccurrence>('/payment-occurrences/' + encodeURIComponent(id), 'PATCH', payload),
  listRecurringPayments: (filters: RecurringPaymentFilters = {}) => request<Page<RecurringPayment>>('/recurring-payments' + query(filters)),
  createRecurringPayment: (payload: CreateRecurringPaymentRequest) => request<RecurringPayment>('/recurring-payments', 'POST', payload),
  stopRecurringPayment: (id: string) => request<void>('/recurring-payments/' + encodeURIComponent(id), 'DELETE'),
  listUsers: (params: PaginationParams = {}) => request<Page<User>>('/users' + query(params)),
  createUser: (payload: CreateUserRequest) => request<User>('/users', 'POST', payload),
  updateUser: (id: string, payload: UpdateUserRequest) => request<User>('/users/' + encodeURIComponent(id), 'PATCH', payload),
  deleteUser: (id: string) => request<void>('/users/' + encodeURIComponent(id), 'DELETE'),
  getSummary: (params: SummaryParams = {}) => request<PaymentSummary>('/payments/summary' + query(params)),
}




