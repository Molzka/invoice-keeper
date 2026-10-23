import type { Currency, ErrorDetail, Page, PaymentOccurrence, RecurringPayment, User } from '../types/api'
import { ADMIN_ID, createFixtures } from './fixtures'
import { businessNowIso, calendarMonthBounds, calendarMonthDate, DEMO_TODAY } from '../config/demo'
export { DEMO_TODAY } from '../config/demo'
const demoMonth = calendarMonthBounds(DEMO_TODAY)

// This transport is a replaceable demo server. Real mode never falls back to it.
const SESSION_KEY = 'invoice-keeper.demo-session.v1'
const demoScenario = () => typeof window === 'undefined' ? '' : new URLSearchParams(window.location.search).get('scenario') || ''
const db = createFixtures(demoScenario() === 'stress')
const passwords = new Map([['admin', 'Admin123!'], ['ivan', 'example-password-only'], ['anna', 'example-password-only']])
let currentUsername: string | null = readSession()
const CSRF = 'demo-session-csrf-only'
function readSession(): string | null { try { return localStorage.getItem(SESSION_KEY) } catch { return null } }
function saveSession(username: string | null) {
  currentUsername = username
  try { if (username) localStorage.setItem(SESSION_KEY, username); else localStorage.removeItem(SESSION_KEY) } catch { /* Private browsers can disable demo persistence. */ }
}
class MockFault extends Error {
  constructor(public status: number, public code: string, message: string, public details: ErrorDetail[] = []) { super(message) }
}
function fault(status: number, code: string, message: string): never { throw new MockFault(status, code, message) }
function invalid(field: string, message: string, code = 'INVALID_VALUE'): never {
  throw new MockFault(422, 'VALIDATION_ERROR', 'Проверьте поля запроса', [{ field, code, message }])
}
function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' } })
}
function wait(ms: number, signal?: AbortSignal | null): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) { reject(new DOMException('Aborted', 'AbortError')); return }
    const abort = () => { clearTimeout(timer); reject(new DOMException('Aborted', 'AbortError')) }
    const timer = setTimeout(() => { signal?.removeEventListener('abort', abort); resolve() }, ms)
    signal?.addEventListener('abort', abort, { once: true })
  })
}
function getCurrentUser(): User { return db.users.find(user => user.username === currentUsername) || fault(401, 'AUTH_REQUIRED', 'Войдите в аккаунт, чтобы продолжить') }
function requireAdmin(user: User) { if (user.role !== 'admin') fault(403, 'FORBIDDEN', 'Действие доступно только администратору') }
function uuid(value: string, field = 'path.id') {
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value)) invalid(field, 'Ожидается корректный UUID')
}
function date(value: unknown, field: string): string {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) invalid(field, 'Введите календарную дату в формате ГГГГ-ММ-ДД')
  const parsed = new Date(value + 'T00:00:00Z')
  if (Number(value.slice(0, 4)) < 1 || Number.isNaN(parsed.valueOf()) || parsed.toISOString().slice(0, 10) !== value) invalid(field, 'Укажите существующую дату')
  return value
}
function queryAllowed(params: URLSearchParams, names: string[]) {
  for (const key of params.keys()) if (!names.includes(key)) invalid(`query.${key}`, 'Неизвестный параметр', 'EXTRA_FIELD')
}
function bodyObject(init: RequestInit, allowed: string[], required: string[] = []): Record<string, unknown> {
  if (!new Headers(init.headers).get('Content-Type')?.toLowerCase().startsWith('application/json')) fault(415, 'UNSUPPORTED_MEDIA_TYPE', 'Ожидается JSON')
  let body: unknown
  try { body = JSON.parse(String(init.body)) } catch { return fault(400, 'INVALID_JSON', 'Не удалось прочитать JSON') }
  if (typeof body !== 'object' || body === null || Array.isArray(body)) invalid('body', 'Ожидается JSON-объект')
  const object = body as Record<string, unknown>
  for (const key of Object.keys(object)) if (!allowed.includes(key)) invalid(key, 'Неизвестное поле', 'EXTRA_FIELD')
  for (const key of required) if (!(key in object)) invalid(key, 'Обязательное поле', 'REQUIRED')
  return object
}
function pagination(params: URLSearchParams): { limit: number; offset: number } {
  const limit = params.has('limit') ? Number(params.get('limit')) : 50
  const offset = params.has('offset') ? Number(params.get('offset')) : 0
  if (!Number.isInteger(limit) || limit < 1 || limit > 100 || params.get('limit') === '') invalid('query.limit', 'От 1 до 100 записей')
  if (!Number.isInteger(offset) || offset < 0 || params.get('offset') === '') invalid('query.offset', 'Смещение должно быть целым неотрицательным числом')
  return { limit, offset }
}
function page<T>(items: T[], params: URLSearchParams): Page<T> { const { limit, offset } = pagination(params); return { items: items.slice(offset, offset + limit), total: items.length, limit, offset } }
function booleanQuery(params: URLSearchParams, key: string): boolean | undefined {
  if (!params.has(key)) return undefined
  const value = params.get(key)
  if (value !== 'true' && value !== 'false') invalid(`query.${key}`, 'Ожидается true или false')
  return value === 'true'
}
function range(params: URLSearchParams, pair = false): { from: string | undefined; to: string | undefined } {
  if (pair && params.has('date_from') !== params.has('date_to')) invalid('query.date_from', 'Укажите обе границы периода')
  const from = params.has('date_from') ? date(params.get('date_from'), 'query.date_from') : undefined
  const to = params.has('date_to') ? date(params.get('date_to'), 'query.date_to') : undefined
  if (from && to && from > to) invalid('query.date_to', 'Конец периода не может быть раньше начала')
  return { from, to }
}
function countDays(from: string, to: string) { return Math.max(0, Math.round((Date.parse(to + 'T00:00:00Z') - Date.parse(from + 'T00:00:00Z')) / 86400000)) }
function occurrenceView(item: PaymentOccurrence): PaymentOccurrence {
  const active = db.recurring.find(rule => rule.id === item.recurring_payment_id)?.is_active ?? false
  return { ...item, is_overdue: item.status === 'unpaid' && item.due_date < DEMO_TODAY,
    paid_late: item.status === 'paid' && item.paid_on !== null && item.paid_on > item.due_date,
    days_late: countDays(item.due_date, item.paid_on || DEMO_TODAY), recurring_payment_is_active: active }
}
function money(value: unknown): string {
  if (typeof value !== 'string' || !/^\d{1,12}\.\d{2}$/.test(value) || BigInt(value.replace('.', '')) < 1n) invalid('amount', 'Передайте положительную сумму строкой с двумя знаками после точки', 'INVALID_MONEY_FORMAT')
  return value
}
function username(value: unknown): string {
  if (typeof value !== 'string' || !/^[a-z0-9_.-]{3,64}$/.test(value)) invalid('username', 'От 3 до 64 символов: a–z, цифры, точка, дефис или подчёркивание')
  return value
}
function password(value: unknown): string { if (typeof value !== 'string' || value.length < 8 || value.length > 128) invalid('password', 'Пароль должен содержать от 8 до 128 символов'); return value }
function advanceMonth(value: string, anchor: number): string { return calendarMonthDate(value, anchor, 1) }
function addOccurrences(rule: RecurringPayment) {
  let due = rule.first_due_date
  const dates: string[] = []
  while (due <= demoMonth.date_to) { dates.push(due); due = advanceMonth(due, rule.anchor_day) }
  if (!dates.some(item => item >= DEMO_TODAY)) dates.push(due)
  rule.next_due_date = dates.find(item => item >= DEMO_TODAY) || due
  dates.forEach(due_date => db.occurrences.push({ id: crypto.randomUUID(), recurring_payment_id: rule.id, title: rule.title,
    amount: rule.amount, currency: rule.currency, due_date, status: 'unpaid', paid_on: null, is_overdue: due_date < DEMO_TODAY,
    paid_late: false, days_late: countDays(due_date, DEMO_TODAY), recurring_payment_is_active: true }))
}
function exactAmount(cents: bigint): string { const text = cents.toString().padStart(3, '0'); return text.slice(0, -2) + '.' + text.slice(-2) }

export async function mockFetch(input: string, init: RequestInit = {}): Promise<Response> {
  const url = new URL(input, typeof window === 'undefined' ? 'http://localhost' : window.location.origin)
  const path = url.pathname.match(/\/(auth|payment-occurrences|recurring-payments|users|payments)(?:\/.*)?$/)?.[0] || url.pathname
  const method = (init.method || 'GET').toUpperCase()
  const scenario = demoScenario()
  const isAuth = path.startsWith('/auth/')
  await wait(scenario === 'slow' && !isAuth ? 15000 : 180, init.signal)
  if (scenario === 'network-error' && !isAuth) throw new TypeError('Demo network failure')
  try {
    if (path === '/auth/login' && method === 'POST') {
      queryAllowed(url.searchParams, [])
      const body = bodyObject(init, ['username', 'password'], ['username', 'password'])
      if (typeof body.username !== 'string' || typeof body.password !== 'string' || passwords.get(body.username) !== body.password || !db.users.some(user => user.username === body.username)) fault(401, 'INVALID_CREDENTIALS', 'Неверный логин или пароль')
      saveSession(body.username as string)
      return json({ user: getCurrentUser(), csrf_token: CSRF })
    }
    const user = getCurrentUser()
    if (path === '/auth/me' && method === 'GET') { queryAllowed(url.searchParams, []); return json({ user, csrf_token: CSRF }) }
    if (['POST', 'PATCH', 'DELETE'].includes(method) && new Headers(init.headers).get('X-CSRF-Token') !== CSRF) fault(403, 'CSRF_FAILED', 'Обновите страницу и повторите действие')
    if (path === '/auth/logout' && method === 'POST') { queryAllowed(url.searchParams, []); saveSession(null); return new Response(null, { status: 204 }) }
    if (scenario === 'forbidden') fault(403, 'FORBIDDEN', 'У вас нет доступа к этому разделу')
    if (path === '/payments/summary' && method === 'GET') {
      queryAllowed(url.searchParams, ['date_from', 'date_to'])
      const { from = demoMonth.date_from, to = demoMonth.date_to } = range(url.searchParams, true)
      if (to > demoMonth.date_to) invalid('query.date_to', 'Сводка доступна по последний день текущего месяца')
      if (scenario === 'periods-not-ready') fault(503, 'PERIODS_NOT_READY', 'Восстанавливаем историю платежей. Сводка появится, когда данные будут полными.')
      const totals = Object.fromEntries((['RUB', 'USD', 'EUR'] as Currency[]).map(currency => {
        const rows = db.occurrences.filter(item => item.currency === currency && item.due_date >= from && item.due_date <= to).map(occurrenceView)
        const sum = (items: PaymentOccurrence[]) => exactAmount(items.reduce((total, item) => total + BigInt(item.amount.replace('.', '')), 0n))
        return [currency, { planned: sum(rows), paid: sum(rows.filter(item => item.status === 'paid')), unpaid: sum(rows.filter(item => item.status === 'unpaid')), overdue: sum(rows.filter(item => item.is_overdue)) }]
      }))
      return json({ date_from: from, date_to: to, as_of_date: DEMO_TODAY, timezone: 'Europe/Moscow', totals })
    }
    if (path === '/payment-occurrences' && method === 'GET') {
      queryAllowed(url.searchParams, ['limit', 'offset', 'date_from', 'date_to', 'status', 'currency', 'recurring_payment_id', 'is_overdue'])
      const { from, to } = range(url.searchParams)
      const status = url.searchParams.get('status'), currency = url.searchParams.get('currency'), ruleId = url.searchParams.get('recurring_payment_id')
      const overdue = booleanQuery(url.searchParams, 'is_overdue')
      if (status !== null && !['paid', 'unpaid'].includes(status)) invalid('query.status', 'Неизвестный статус')
      if (currency !== null && !['RUB', 'USD', 'EUR'].includes(currency)) invalid('query.currency', 'Выберите RUB, USD или EUR')
      if (ruleId !== null) uuid(ruleId, 'query.recurring_payment_id')
      const items = db.occurrences.map(occurrenceView).filter(item => (!from || item.due_date >= from) && (!to || item.due_date <= to) && (!status || item.status === status) && (!currency || item.currency === currency) && (!ruleId || item.recurring_payment_id === ruleId) && (overdue === undefined || item.is_overdue === overdue)).sort((a, b) => a.due_date.localeCompare(b.due_date) || a.id.localeCompare(b.id))
      return json(page(items, url.searchParams))
    }
    if (path.startsWith('/payment-occurrences/')) {
      queryAllowed(url.searchParams, [])
      const id = path.split('/').at(-1)!
      uuid(id)
      const item = db.occurrences.find(row => row.id === id) || fault(404, 'PAYMENT_OCCURRENCE_NOT_FOUND', 'Период не найден')
      if (method === 'GET') return json(occurrenceView(item))
      if (method === 'PATCH') {
        const body = bodyObject(init, ['status', 'paid_on'], ['status', 'paid_on'])
        if (body.status !== 'paid' && body.status !== 'unpaid') invalid('status', 'Выберите paid или unpaid')
        if (body.status === 'unpaid') { if (body.paid_on !== null) invalid('paid_on', 'При отмене оплаты дата должна быть null') }
        else { const paidOn = date(body.paid_on, 'paid_on'); if (paidOn > DEMO_TODAY) invalid('paid_on', 'Фактическая дата не может быть позже сегодняшнего дня по МСК') }
        item.status = body.status as 'paid' | 'unpaid'; item.paid_on = body.paid_on as string | null
        return json(occurrenceView(item))
      }
    }
    if (path === '/recurring-payments') {
      if (method === 'GET') {
        queryAllowed(url.searchParams, ['limit', 'offset', 'is_active'])
        const active = booleanQuery(url.searchParams, 'is_active')
        return json(page(db.recurring.filter(item => active === undefined || item.is_active === active).sort((a, b) => b.created_at.localeCompare(a.created_at) || a.id.localeCompare(b.id)), url.searchParams))
      }
      if (method === 'POST') {
        requireAdmin(user); queryAllowed(url.searchParams, [])
        const body = bodyObject(init, ['title', 'amount', 'currency', 'first_due_date', 'periodicity'], ['title', 'amount', 'currency', 'first_due_date', 'periodicity'])
        if (typeof body.title !== 'string' || body.title.trim().length < 1 || body.title.trim().length > 200) invalid('title', 'Название должно содержать от 1 до 200 символов')
        const amount = money(body.amount), firstDue = date(body.first_due_date, 'first_due_date')
        if (typeof body.currency !== 'string' || !['RUB', 'USD', 'EUR'].includes(body.currency)) invalid('currency', 'Выберите RUB, USD или EUR')
        if (body.periodicity !== 'monthly') invalid('periodicity', 'Поддерживается ежемесячное повторение')
        const item: RecurringPayment = { id: crypto.randomUUID(), title: (body.title as string).trim(), amount, currency: body.currency as Currency, first_due_date: firstDue, next_due_date: firstDue, periodicity: 'monthly', anchor_day: Number(firstDue.slice(-2)), is_active: true, created_at: businessNowIso('mock') }
        addOccurrences(item); db.recurring.push(item)
        return json(item, 201)
      }
    }
    if (path.startsWith('/recurring-payments/') && method === 'DELETE') {
      requireAdmin(user); queryAllowed(url.searchParams, [])
      const id = path.split('/').at(-1)!; uuid(id)
      const item = db.recurring.find(row => row.id === id) || fault(404, 'RECURRING_PAYMENT_NOT_FOUND', 'Регулярный платёж не найден')
      item.is_active = false; item.next_due_date = null
      return new Response(null, { status: 204 })
    }
    if (path === '/users' || path.startsWith('/users/')) {
      requireAdmin(user)
      if (path === '/users' && method === 'GET') {
        queryAllowed(url.searchParams, ['limit', 'offset'])
        return json(page(db.users.filter(item => item.role === 'user').sort((a, b) => a.username.localeCompare(b.username) || a.id.localeCompare(b.id)), url.searchParams))
      }
      queryAllowed(url.searchParams, [])
      if (path === '/users' && method === 'POST') {
        const body = bodyObject(init, ['username', 'password'], ['username', 'password'])
        const name = username(body.username), secret = password(body.password)
        if (db.users.some(item => item.username === name)) fault(409, 'USERNAME_TAKEN', 'Этот логин уже занят')
        const item: User = { id: crypto.randomUUID(), username: name, role: 'user', created_at: businessNowIso('mock') }
        db.users.push(item); passwords.set(name, secret); return json(item, 201)
      }
      const id = path.split('/').at(-1)!; uuid(id)
      if (id === ADMIN_ID) fault(403, 'ADMIN_ACCOUNT_PROTECTED', 'Учётной записью администратора управляют через настройки сервера')
      const item = db.users.find(row => row.id === id) || fault(404, 'USER_NOT_FOUND', 'Пользователь не найден')
      if (method === 'PATCH') {
        const body = bodyObject(init, ['username', 'password'])
        if (Object.keys(body).length === 0) invalid('body', 'Укажите логин и/или пароль')
        const name = 'username' in body ? username(body.username) : item.username
        if (db.users.some(row => row.id !== id && row.username === name)) fault(409, 'USERNAME_TAKEN', 'Этот логин уже занят')
        const secret = 'password' in body ? password(body.password) : passwords.get(item.username)!
        passwords.delete(item.username); passwords.set(name, secret); item.username = name
        return json(item)
      }
      if (method === 'DELETE') { db.users.splice(db.users.indexOf(item), 1); passwords.delete(item.username); return new Response(null, { status: 204 }) }
    }
    return fault(404, 'NOT_FOUND', 'Маршрут не найден')
  } catch (error) {
    if (error instanceof MockFault) return json({ error: { code: error.code, message: error.message, details: error.details } }, error.status)
    throw error
  }
}


