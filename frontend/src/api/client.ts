import type {
  AuthResponse, CreateRecurringPaymentRequest, CreateUserRequest, ErrorDetail, ErrorResponse,
  LoginRequest, OccurrenceFilters, Page, PaginationParams, PaymentOccurrence, PaymentSummary,
  RecurringPayment, RecurringPaymentFilters, SummaryParams, UpdateOccurrenceRequest, UpdateUserRequest, User,
} from '../types/api'
import { mockFetch } from '../mocks/transport'

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public details: ErrorDetail[] = []) {
    super(message); this.name = 'ApiError'
  }
}
export const API_MODE = import.meta.env.VITE_API_MODE === 'real' ? 'real' : 'mock'
const BASE_URL = (import.meta.env.VITE_API_BASE_URL || '/api/v1').replace(/\/$/, '')
const REQUEST_TIMEOUT_MS = 12000
let csrfToken: string | null = null
const transport = API_MODE === 'real' ? (url: string, init: RequestInit) => fetch(url, init) : mockFetch
function query(params?: object): string {
  const search = new URLSearchParams()
  Object.entries(params || {}).forEach(([key, value]) => { if (value !== undefined && value !== null && value !== '') search.set(key, String(value)) })
  return search.size ? '?' + search.toString() : ''
}
async function request<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
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
      if (response.status === 401) { csrfToken = null; window.dispatchEvent(new CustomEvent('invoice:unauthorized')) }
      // A disconnected or timed-out response body still has an unknown mutation outcome.
      if (abort.signal.aborted || error instanceof TypeError) throw error
      throw new ApiError(response.status, 'INVALID_RESPONSE', 'Сервер вернул ответ в неизвестном формате')
    }
    if (!response.ok) {
      const serverError = (payload as Partial<ErrorResponse>)?.error
      const error = new ApiError(response.status, serverError?.code || 'HTTP_ERROR', serverError?.message || 'Не удалось выполнить запрос', Array.isArray(serverError?.details) ? serverError.details : [])
      if (response.status === 401 && !(path === '/auth/login' && error.code === 'INVALID_CREDENTIALS')) {
        csrfToken = null
        window.dispatchEvent(new CustomEvent('invoice:unauthorized'))
      }
      throw error
    }
    return payload as T
  } catch (error) {
    if (error instanceof ApiError) throw error
    if (abort.signal.aborted) throw new ApiError(0, 'TIMEOUT', 'Сервер не ответил вовремя. Перед повторным созданием проверьте список: запись могла сохраниться.')
    throw new ApiError(0, 'NETWORK_ERROR', 'Нет связи с сервером. Проверьте подключение и попробуйте ещё раз.')
  } finally { clearTimeout(timeout) }
}

export const api = {
  async login(payload: LoginRequest): Promise<AuthResponse> { const data = await request<AuthResponse>('/auth/login', 'POST', payload); csrfToken = data.csrf_token; return data },
  async me(): Promise<AuthResponse> { const data = await request<AuthResponse>('/auth/me'); csrfToken = data.csrf_token; return data },
  async logout(): Promise<void> { await request<void>('/auth/logout', 'POST'); csrfToken = null },
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



