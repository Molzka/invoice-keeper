import { AUDIT_ACTIONS } from '../types/activity'
import type { AuditAction } from '../types/activity'
import { createAuditFixtures, createAuditStore } from './activity'
import type { PaymentReceipt } from '../types/extras'
import type { Currency, ErrorDetail, Page, PaymentOccurrence, RecurringPayment, User } from '../types/api'
import { ADMIN_ID, createFixtures } from './fixtures'
import { APP_TIMEZONE, businessNowIso, calendarMonthBounds, calendarMonthDate, DEMO_TODAY } from '../config/demo'
export { DEMO_TODAY } from '../config/demo'
const receipts = new Map<string, { receipt: PaymentReceipt; file?: Blob }>()
const demoMonth = calendarMonthBounds(DEMO_TODAY)

// This transport is a replaceable demo server. Real mode never falls back to it.
const SESSION_KEY = 'invoice-keeper.demo-session.v1'
const demoScenario = () => typeof window === 'undefined' ? '' : new URLSearchParams(window.location.search).get('scenario') || ''
const db = createFixtures(demoScenario() === 'stress')
const audit = createAuditStore(createAuditFixtures(db.users, db.recurring, db.occurrences))
const passwords = new Map([['admin', 'Admin123!'], ['ivan', 'example-password-only'], ['anna', 'example-password-only']])
let currentUsername: string | null = readSession()
let csrfToken = crypto.randomUUID()
const passwordChangeAttempts = new Map<string, number[]>()
let passwordScenarioUsed = false
const PASSWORD_CHANGE_WINDOW_MS = 15 * 60 * 1000
const PASSWORD_CHANGE_ATTEMPTS = 5
function readSession(): string | null { try { return localStorage.getItem(SESSION_KEY) } catch { return null } }
function saveSession(username: string | null) {
  currentUsername = username
  try { if (username) localStorage.setItem(SESSION_KEY, username); else localStorage.removeItem(SESSION_KEY) } catch { /* Private browsers can disable demo persistence. */ }
}
class MockFault extends Error {
  constructor(public status: number, public code: string, message: string, public details: ErrorDetail[] = [], public retryAfterSeconds?: number) { super(message) }
}
function fault(status: number, code: string, message: string): never { throw new MockFault(status, code, message) }
function invalid(field: string, message: string, code = 'INVALID_VALUE'): never {
  throw new MockFault(422, 'VALIDATION_ERROR', 'Проверьте поля запроса', [{ field, code, message }])
}
function json(data: unknown, status = 200, retryAfterSeconds?: number): Response {
  return new Response(JSON.stringify(data), { status, headers: { ...(retryAfterSeconds === undefined ? {} : { 'Retry-After': String(retryAfterSeconds) }), 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' } })
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
  const rule = db.recurring.find(rule => rule.id === item.recurring_payment_id)
  return { ...item, title: rule?.title || item.title, periodicity: rule?.periodicity || item.periodicity, is_overdue: item.status === 'unpaid' && item.due_date < DEMO_TODAY,
    paid_late: item.status === 'paid' && item.paid_on !== null && item.paid_on > item.due_date,
    days_late: countDays(item.due_date, item.paid_on || DEMO_TODAY), recurring_payment_is_active: rule?.is_active ?? false }
}
function paymentTitle(value: unknown): string {
  if (typeof value !== 'string' || !value.trim() || Array.from(value.trim()).length > 200 || value.includes('\0')) invalid('title', 'Введите название от 1 до 200 символов.')
  return value.trim()
}
function money(value: unknown): string {
  if (typeof value !== 'string' || !/^\d{1,12}\.\d{2}$/.test(value) || BigInt(value.replace('.', '')) < 1n) invalid('amount', 'Передайте положительную сумму строкой с двумя знаками после точки', 'INVALID_MONEY_FORMAT')
  return value
}
function username(value: unknown): string {
  if (typeof value !== 'string' || !/^[a-z0-9_.-]{3,64}$/.test(value)) invalid('username', 'От 3 до 64 символов: a–z, цифры, точка, дефис или подчёркивание')
  return value
}
function password(value: unknown): string { if (typeof value !== 'string' || Array.from(value).length < 8 || Array.from(value).length > 128) invalid('password', 'Пароль должен содержать от 8 до 128 символов'); return value }
function passwordChangeValue(value: unknown, field: string, minimum: number): string {
  if (typeof value !== 'string' || Array.from(value).length < minimum || Array.from(value).length > 128) invalid(field, `Пароль должен содержать от ${minimum} до 128 символов`)
  return value
}
function recordPasswordChangeAttempt(userId: string) {
  const now = Date.now()
  const attempts = (passwordChangeAttempts.get(userId) || []).filter(at => at > now - PASSWORD_CHANGE_WINDOW_MS)
  if (attempts.length >= PASSWORD_CHANGE_ATTEMPTS) {
    const seconds = Math.max(1, Math.ceil((attempts[0] + PASSWORD_CHANGE_WINDOW_MS - now) / 1000))
    throw new MockFault(429, 'PASSWORD_CHANGE_RATE_LIMITED', 'Слишком много попыток смены пароля. Попробуйте позже.', [], seconds)
  }
  passwordChangeAttempts.set(userId, [...attempts, now])
}
function advanceMonth(value: string, anchor: number): string { return calendarMonthDate(value, anchor, 1) }
function addOccurrences(rule: RecurringPayment) {
  let due = rule.first_due_date
  const dates: string[] = []
  while (due <= demoMonth.date_to) { dates.push(due); due = advanceMonth(due, rule.anchor_day) }
  if (!dates.some(item => item >= DEMO_TODAY)) dates.push(due)
  rule.next_due_date = dates.find(item => item >= DEMO_TODAY) || due
  dates.filter(due => !db.occurrences.some(item => item.recurring_payment_id === rule.id && item.due_date === due)).forEach(due_date => db.occurrences.push({ id: crypto.randomUUID(), recurring_payment_id: rule.id, title: rule.title,
    amount: rule.amount, currency: rule.currency, due_date, status: 'unpaid', paid_on: null, is_overdue: due_date < DEMO_TODAY,
    paid_late: false, days_late: countDays(due_date, DEMO_TODAY), recurring_payment_is_active: true, amount_is_custom: false }))
}
function exactAmount(cents: bigint): string { const text = cents.toString().padStart(3, '0'); return text.slice(0, -2) + '.' + text.slice(-2) }

export async function mockFetch(input: string, init: RequestInit = {}): Promise<Response> {
  const url = new URL(input, typeof window === 'undefined' ? 'http://localhost' : window.location.origin)
  const path = url.pathname.match(/\/(auth|one-time-payments|payment-receipts|payment-occurrences|recurring-payments|users|payments|audit-events)(?:\/.*)?$/)?.[0] || url.pathname
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
      csrfToken = crypto.randomUUID()
      return json({ user: getCurrentUser(), csrf_token: csrfToken, timezone: APP_TIMEZONE })
    }
    const user = getCurrentUser()
    if (path === '/auth/me' && method === 'GET') { queryAllowed(url.searchParams, []); return json({ user, csrf_token: csrfToken, timezone: APP_TIMEZONE }) }
    if (path === '/auth/change-password' && method === 'POST' && scenario === 'password-csrf' && !passwordScenarioUsed) {
      passwordScenarioUsed = true; csrfToken = crypto.randomUUID(); fault(403, 'CSRF_FAILED', 'Обновите сессию и повторите действие')
    }
    if (path === '/auth/change-password' && method === 'POST' && scenario === 'password-account-changed' && !passwordScenarioUsed) {
      passwordScenarioUsed = true
      saveSession(user.username === 'admin' ? 'ivan' : 'admin')
      csrfToken = crypto.randomUUID()
      fault(403, 'CSRF_FAILED', 'Учётная запись в текущем браузере изменилась')
    }
    if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(method) && new Headers(init.headers).get('X-CSRF-Token') !== csrfToken) fault(403, 'CSRF_FAILED', 'Обновите страницу и повторите действие')
    if (path === '/auth/logout' && method === 'POST') { queryAllowed(url.searchParams, []); saveSession(null); return new Response(null, { status: 204 }) }
    if (path === '/auth/change-password' && method === 'POST') {
      if (user.role === 'admin') fault(403, 'ADMIN_ACCOUNT_PROTECTED', 'Учётная запись администратора изменяется только в конфигурации сервера')
      queryAllowed(url.searchParams, [])
      const body = bodyObject(init, ['current_password', 'new_password'], ['current_password', 'new_password'])
      const currentPassword = passwordChangeValue(body.current_password, 'current_password', 1)
      const newPassword = passwordChangeValue(body.new_password, 'new_password', 8)
      recordPasswordChangeAttempt(user.id)
      if (passwords.get(user.username) !== currentPassword) throw new MockFault(422, 'CURRENT_PASSWORD_INVALID', 'Текущий пароль указан неверно', [{ field: 'current_password', code: 'CURRENT_PASSWORD_INVALID', message: 'Текущий пароль указан неверно' }])
      if (newPassword === currentPassword) throw new MockFault(422, 'NEW_PASSWORD_UNCHANGED', 'Новый пароль должен отличаться от текущего', [{ field: 'new_password', code: 'NEW_PASSWORD_UNCHANGED', message: 'Новый пароль должен отличаться от текущего' }])
      // Demo secrets are deliberately memory-only: a reload restores the example credentials.
      passwords.set(user.username, newPassword)
      audit.append({ actor: user, action: 'password.changed', entity: { type: 'account', id: user.id, title: user.username } })
      csrfToken = crypto.randomUUID()
      if (scenario === 'password-network' && !passwordScenarioUsed) { passwordScenarioUsed = true; throw new TypeError('Demo password response lost') }
      return json({ user, csrf_token: csrfToken, timezone: APP_TIMEZONE })
    }
    if (scenario === 'forbidden') fault(403, 'FORBIDDEN', 'У вас нет доступа к этому разделу')
    if (path === '/audit-events' && method === 'GET') {
      requireAdmin(user)
      queryAllowed(url.searchParams, ['date_from', 'date_to', 'actor', 'action', 'query', 'limit', 'offset'])
      const { from = '', to = '' } = range(url.searchParams)
      const action = url.searchParams.get('action') || ''
      if (action && !(AUDIT_ACTIONS as readonly string[]).includes(action)) invalid('query.action', 'Неизвестное действие')
      const actor = url.searchParams.get('actor') || '', query = url.searchParams.get('query') || ''
      if (actor.length > 64) invalid('query.actor', 'Не более 64 символов')
      if (query.length > 200) invalid('query.query', 'Не более 200 символов')
      const paging = pagination(url.searchParams)
      if (scenario === 'audit-error') fault(503, 'AUDIT_TEMPORARILY_UNAVAILABLE', 'Журнал временно недоступен. Повторите загрузку позже.')
      if (scenario === 'audit-empty') return json({ items: [], total: 0, ...paging })
      return json(audit.list({ date_from: from, date_to: to, actor, action: action as AuditAction | '', query, ...paging }))
    }

    if (path === '/payments/budget' && method === 'GET') {
      queryAllowed(url.searchParams, ['year', 'month'])
      const year = Number(url.searchParams.get('year')), month = url.searchParams.has('month') ? Number(url.searchParams.get('month')) : null
      if (!Number.isInteger(year) || year < 1 || year > 9999) invalid('query.year', 'Год от 1 до 9999')
      if (month !== null && (!Number.isInteger(month) || month < 1 || month > 12)) invalid('query.month', 'Месяц от 1 до 12')
      if (scenario === 'periods-not-ready') fault(503, 'PERIODS_NOT_READY', 'История периодов ещё восстанавливается')
      const months = (month ? [month] : Array.from({ length: 12 }, (_, index) => index + 1)).map(number => {
        const prefix = `${String(year).padStart(4,'0')}-${String(number).padStart(2,'0')}`
        const totals = Object.fromEntries((['RUB','USD','EUR'] as Currency[]).map(currency => [currency, { planned:0n, paid:0n, unpaid:0n, overdue:0n, forecast:0n }])) as Record<Currency, Record<'planned'|'paid'|'unpaid'|'overdue'|'forecast', bigint>>
        for (const item of db.occurrences.filter(item => item.due_date.startsWith(prefix) && !item.is_cancelled)) {
          const total = totals[item.currency], value = BigInt(item.amount.replace('.',''))
          total.planned += value; total[item.status] += value
          if (item.status === 'unpaid' && item.due_date < DEMO_TODAY) total.overdue += value
        }
        for (const rule of db.recurring.filter(rule => rule.is_active && !rule.is_archived && rule.periodicity === 'monthly')) {
          const due = calendarMonthDate(`${prefix}-01`, rule.anchor_day)
          if (due >= rule.first_due_date && due > demoMonth.date_to && !db.occurrences.some(item => item.recurring_payment_id === rule.id && item.due_date === due)) {
            const value = BigInt(rule.amount.replace('.','')); totals[rule.currency].planned += value; totals[rule.currency].forecast += value
          }
        }
        return { month: number, totals }
      })
      const total = Object.fromEntries((['RUB','USD','EUR'] as Currency[]).map(currency => [currency, Object.fromEntries(['planned','paid','unpaid','overdue','forecast'].map(field => [field, exactAmount(months.reduce((sum, item) => sum + item.totals[currency][field as 'planned'], 0n))]))]))
      return json({ year, month, date_from:`${String(year).padStart(4,'0')}-${String(month || 1).padStart(2,'0')}-01`, date_to:calendarMonthBounds(`${String(year).padStart(4,'0')}-${String(month || 12).padStart(2,'0')}-01`).date_to, as_of_date:DEMO_TODAY, timezone:APP_TIMEZONE, totals:total, months:months.map(item => ({ month:item.month, totals:Object.fromEntries(Object.entries(item.totals).map(([currency, values]) => [currency, Object.fromEntries(Object.entries(values).map(([key,value]) => [key,exactAmount(value)]))])) })) })
    }
    if (path === '/one-time-payments' && method === 'POST') {
      requireAdmin(user); queryAllowed(url.searchParams, [])
      const body = bodyObject(init, ['title','amount','currency','due_date'], ['title','amount','currency','due_date'])
      if (typeof body.title !== 'string' || !body.title.trim() || body.title.trim().length > 200) invalid('title', 'Название от 1 до 200 символов')
      const amount = money(body.amount), due = date(body.due_date, 'due_date')
      if (typeof body.currency !== 'string' || !['RUB','USD','EUR'].includes(body.currency)) invalid('currency', 'Выберите валюту')
      const rule: RecurringPayment = { id:crypto.randomUUID(), title:body.title.trim(), amount, currency:body.currency as Currency, first_due_date:due, next_due_date:due >= DEMO_TODAY ? due : null, periodicity:'once', anchor_day:Number(due.slice(-2)), is_active:true, created_at:businessNowIso('mock'), amount_effective_from:null }
      db.recurring.push(rule)
      const occurrence: PaymentOccurrence = { id:crypto.randomUUID(), recurring_payment_id:rule.id, title:rule.title, amount, currency:rule.currency, due_date:due, status:'unpaid', paid_on:null, periodicity:'once', is_cancelled:false, is_overdue:due < DEMO_TODAY, paid_late:false, days_late:countDays(due,DEMO_TODAY), recurring_payment_is_active:true, amount_is_custom:false }
      db.occurrences.push(occurrence)
      audit.append({actor:user, action:'payment.created', entity:{type:'payment', id:rule.id, title:rule.title}, changes:[{field:'due_date',label:'Разовый срок',before:null,after:due}]})
      return json(occurrenceView(occurrence),201)
    }
    if (/^\/recurring-payments\/[^/]+\/archive$/.test(path) && method === 'POST') {
      requireAdmin(user); queryAllowed(url.searchParams, [])
      const id = path.split('/')[2]; uuid(id)
      const rule = db.recurring.find(rule => rule.id === id) || fault(404,'RECURRING_PAYMENT_NOT_FOUND','Платёж не найден')
      if (!rule.is_archived) {
        rule.is_archived = true; rule.is_active = false; rule.next_due_date = null
        for (const item of db.occurrences.filter(item => item.recurring_payment_id === id && item.status === 'unpaid')) item.is_cancelled = true
        audit.append({actor:user, action:'payment.deleted', entity:{type:'payment',id,title:rule.title}, changes:[{field:'is_archived',label:'Удалён',before:'false',after:'true'}]})
      }
      return new Response(null,{status:204})
    }
    if (/^\/payment-occurrences\/[^/]+$/.test(path) && method === 'DELETE') {
      requireAdmin(user); queryAllowed(url.searchParams, [])
      const id = path.split('/')[2]; uuid(id)
      const item = db.occurrences.find(item => item.id === id) || fault(404,'PAYMENT_OCCURRENCE_NOT_FOUND','Период не найден')
      if (item.status === 'paid') fault(409,'PAYMENT_ALREADY_PAID','Сначала отмените отметку оплаты')
      if (!item.is_cancelled) {
        item.is_cancelled = true
        const rule = db.recurring.find(rule => rule.id === item.recurring_payment_id)
        if (rule?.periodicity === 'once') { rule.is_active = false; rule.is_archived = true }
        audit.append({actor:user,action:'payment.period_deleted',entity:{type:'payment',id:item.recurring_payment_id,title:item.title},changes:[{field:'is_cancelled',label:'Удалён',before:'false',after:'true'}]})
      }
      return new Response(null,{status:204})
    }
    if (path === '/payment-receipts' && method === 'GET') {
      queryAllowed(url.searchParams,['query','currency','kind','limit','offset'])
      const query = (url.searchParams.get('query') || '').trim().toLocaleLowerCase('ru'), kind = url.searchParams.get('kind') || 'all', currency = url.searchParams.get('currency') || ''
      if (query.length > 200 || !['all','file','link','missing'].includes(kind)) invalid('query','Неверный фильтр')
      if (currency && !['RUB','USD','EUR'].includes(currency)) invalid('query.currency','Выберите валюту')
      const rows = db.occurrences.filter(item => !item.is_cancelled).map(occurrence => ({occurrence:occurrenceView(occurrence),receipt:receipts.get(occurrence.id)?.receipt || null})).filter(({occurrence,receipt}) => (!currency || occurrence.currency === currency) && (kind === 'all' || kind === 'missing' ? kind !== 'missing' || !receipt : receipt?.kind === kind) && (!query || [occurrence.title,receipt?.filename,receipt?.url].some(value => value?.toLocaleLowerCase('ru').includes(query)))).sort((a,b) => b.occurrence.due_date.localeCompare(a.occurrence.due_date) || a.occurrence.id.localeCompare(b.occurrence.id))
      return json(page(rows,url.searchParams))
    }
    if (/^\/payment-occurrences\/[^/]+\/receipt(?:\/file)?$/.test(path)) {
      queryAllowed(url.searchParams,[])
      const id = path.split('/')[2]; uuid(id)
      const occurrence = db.occurrences.find(item => item.id === id) || fault(404,'PAYMENT_OCCURRENCE_NOT_FOUND','Период не найден')
      const stored = receipts.get(id)
      if (method === 'GET') {
        if (path.endsWith('/file')) return stored?.file ? new Response(stored.file,{headers:{'Content-Type':stored.receipt.content_type!,'Cache-Control':'no-store'}}) : fault(404,'RECEIPT_FILE_NOT_FOUND','Файл не найден')
        return json(stored?.receipt || null)
      }
      if (occurrence.is_cancelled) fault(409,'PAYMENT_CANCELLED','Период удалён')
      if (method === 'DELETE') {
        if (receipts.delete(id)) audit.append({actor:user,action:'payment.receipt_deleted',entity:{type:'payment',id:occurrence.recurring_payment_id,title:occurrence.title},changes:[{field:'receipt',label:'Чек',before:stored?.receipt.kind || null,after:null}]})
        return new Response(null,{status:204})
      }
      if (method === 'PUT') {
        let value: {receipt:PaymentReceipt;file?:Blob}
        const type = new Headers(init.headers).get('Content-Type') || ''
        if (type === 'application/json') {
          const body = bodyObject(init,['url'],['url'])
          let valid = false
          try { const link = new URL(String(body.url)); valid = typeof body.url === 'string' && body.url.length <= 2048 && !Array.from(body.url).some(character => character.charCodeAt(0) <= 32 || character.charCodeAt(0) === 127 || character === '\\') && link.protocol === 'https:' && !link.username && !link.password } catch { /* validation below */ }
          if (!valid) invalid('url','Укажите корректную HTTPS-ссылку')
          value = {receipt:{id:stored?.receipt.id || crypto.randomUUID(),kind:'link',url:body.url as string,filename:null,content_type:null,size_bytes:null,uploaded_at:businessNowIso('mock')}}
        } else {
          if (!['application/pdf','image/png','image/jpeg'].includes(type)) fault(415,'UNSUPPORTED_RECEIPT_TYPE','Разрешены PDF, PNG, JPEG')
          const blob = init.body instanceof Blob ? init.body : null
          if (!blob || !blob.size) invalid('file','Выберите непустой файл')
          if (blob.size > 5 * 1024 * 1024) fault(413,'RECEIPT_TOO_LARGE','Не более 5 МиБ')
          const bytes = new Uint8Array(await blob.slice(0,8).arrayBuffer()), signatures:Record<string,number[]> = {'application/pdf':[37,80,68,70,45],'image/png':[137,80,78,71,13,10,26,10],'image/jpeg':[255,216,255]}
          if (!signatures[type].every((value,index) => bytes[index] === value)) invalid('file','Содержимое не соответствует формату')
          const name = decodeURIComponent(new Headers(init.headers).get('X-Filename') || 'receipt').replaceAll('\\','/').split('/').at(-1)!.split('').filter(character => character.charCodeAt(0) >= 32 && character.charCodeAt(0) !== 127).join('').slice(0,160)
          value = {receipt:{id:stored?.receipt.id || crypto.randomUUID(),kind:'file',url:null,filename:name,content_type:type as PaymentReceipt['content_type'],size_bytes:blob.size,uploaded_at:businessNowIso('mock')},file:blob}
        }
        receipts.set(id,value)
        audit.append({actor:user,action:'payment.receipt_updated',entity:{type:'payment',id:occurrence.recurring_payment_id,title:occurrence.title},changes:[{field:'receipt',label:'Чек',before:stored?.receipt.kind || null,after:value.receipt.kind}]})
        return json(value.receipt)
      }
    }

    if (path === '/payments/summary' && method === 'GET') {
      queryAllowed(url.searchParams, ['date_from', 'date_to'])
      const { from = demoMonth.date_from, to = demoMonth.date_to } = range(url.searchParams, true)
      if (to > demoMonth.date_to) invalid('query.date_to', 'Сводка доступна по последний день текущего месяца')
      if (scenario === 'periods-not-ready') fault(503, 'PERIODS_NOT_READY', 'Восстанавливаем историю платежей. Сводка появится, когда данные будут полными.')
      const totals = Object.fromEntries((['RUB', 'USD', 'EUR'] as Currency[]).map(currency => {
        const rows = db.occurrences.filter(item => !item.is_cancelled && item.currency === currency && item.due_date >= from && item.due_date <= to).map(occurrenceView)
        const sum = (items: PaymentOccurrence[]) => exactAmount(items.reduce((total, item) => total + BigInt(item.amount.replace('.', '')), 0n))
        return [currency, { planned: sum(rows), paid: sum(rows.filter(item => item.status === 'paid')), unpaid: sum(rows.filter(item => item.status === 'unpaid')), overdue: sum(rows.filter(item => item.is_overdue)) }]
      }))
      return json({ date_from: from, date_to: to, as_of_date: DEMO_TODAY, timezone: 'Europe/Moscow', totals })
    }
    if (path === '/payment-occurrences' && method === 'GET') {
      queryAllowed(url.searchParams, ['limit', 'offset', 'date_from', 'date_to', 'status', 'currency', 'recurring_payment_id', 'is_overdue', 'include_cancelled'])
      const { from, to } = range(url.searchParams)
      const status = url.searchParams.get('status'), currency = url.searchParams.get('currency'), ruleId = url.searchParams.get('recurring_payment_id')
      const overdue = booleanQuery(url.searchParams, 'is_overdue')
      if (status !== null && !['paid', 'unpaid'].includes(status)) invalid('query.status', 'Неизвестный статус')
      if (currency !== null && !['RUB', 'USD', 'EUR'].includes(currency)) invalid('query.currency', 'Выберите RUB, USD или EUR')
      if (ruleId !== null) uuid(ruleId, 'query.recurring_payment_id')
      const items = db.occurrences.map(occurrenceView).filter(item => (booleanQuery(url.searchParams, 'include_cancelled') || !item.is_cancelled) && (!from || item.due_date >= from) && (!to || item.due_date <= to) && (!status || item.status === status) && (!currency || item.currency === currency) && (!ruleId || item.recurring_payment_id === ruleId) && (overdue === undefined || item.is_overdue === overdue)).sort((a, b) => a.due_date.localeCompare(b.due_date) || a.id.localeCompare(b.id))
      return json(page(items, url.searchParams))
    }
    if (/^\/payment-occurrences\/[^/]+\/details$/.test(path) && method === 'PATCH') {
      requireAdmin(user); queryAllowed(url.searchParams, [])
      const id = path.split('/')[2]; uuid(id)
      const body = bodyObject(init, ['title', 'amount', 'currency', 'periodicity'], ['title'])
      const title = paymentTitle(body.title)
      const hasAmount = 'amount' in body || 'currency' in body
      const amount = hasAmount ? money(body.amount) : undefined
      if (hasAmount && (typeof body.currency !== 'string' || !['RUB', 'USD', 'EUR'].includes(body.currency))) invalid('currency', 'Выберите RUB, USD или EUR')
      if ('periodicity' in body && body.periodicity !== 'monthly') invalid('periodicity', 'Выберите ежемесячное повторение')
      const item = db.occurrences.find(row => row.id === id) || fault(404, 'PAYMENT_OCCURRENCE_NOT_FOUND', 'Период не найден')
      const rule = db.recurring.find(row => row.id === item.recurring_payment_id)!
      if (item.is_cancelled) fault(409, 'PAYMENT_CANCELLED', 'Период удалён')
      if (hasAmount && item.status === 'paid') fault(409, 'PAYMENT_ALREADY_PAID', 'Сумму и валюту оплаченного периода изменить нельзя')
      const converting = body.periodicity === 'monthly' && rule.periodicity === 'once'
      if (converting && (!rule.is_active || rule.is_archived)) fault(409, 'RECURRING_PAYMENT_STOPPED', 'Удалённый платёж нельзя повторять')
      const changes = [{ field: 'title', label: 'Название', before: rule.title, after: title }]
      if (amount !== undefined && (item.amount !== amount || item.currency !== body.currency)) {
        changes.push({ field: 'amount', label: 'Сумма', before: item.amount, after: amount }, { field: 'currency', label: 'Валюта', before: item.currency, after: body.currency as string })
        item.amount = amount; item.currency = body.currency as Currency; item.amount_is_custom = true
      }
      rule.title = title
      for (const period of db.occurrences.filter(row => row.recurring_payment_id === rule.id)) period.title = title
      if (rule.periodicity === 'once') { rule.amount = item.amount; rule.currency = item.currency }
      if (converting) {
        rule.periodicity = 'monthly'; addOccurrences(rule)
        changes.push({ field: 'periodicity', label: 'Повторение', before: 'Разовый', after: 'Ежемесячный' })
      }
      if (changes.some(change => change.before !== change.after)) audit.append({ actor: user, action: 'payment.terms_changed', entity: { type: 'payment', id: rule.id, title }, changes })
      return json(occurrenceView(item))
    }
    if (/^\/payment-occurrences\/[^/]+\/amount$/.test(path) && method === 'PATCH') {
      requireAdmin(user); queryAllowed(url.searchParams, [])
      const id = path.split('/')[2]; uuid(id)
      const body = bodyObject(init, ['amount', 'currency'], ['amount', 'currency'])
      const amount = exactAmount(BigInt(money(body.amount).replace('.', '')))
      if (typeof body.currency !== 'string' || !['RUB', 'USD', 'EUR'].includes(body.currency)) invalid('currency', 'Выберите RUB, USD или EUR')
      const currency = body.currency as Currency
      const item = db.occurrences.find(row => row.id === id) || fault(404, 'PAYMENT_OCCURRENCE_NOT_FOUND', 'Период не найден')
      if (item.is_cancelled) fault(409, 'PAYMENT_CANCELLED', 'Период удалён и доступен только для просмотра')
      if (item.status === 'paid') fault(409, 'PAYMENT_ALREADY_PAID', 'Сумму и валюту оплаченного периода изменить нельзя')
      if (item.amount !== amount || item.currency !== currency) {
        const oldAmount = item.amount, oldCurrency = item.currency
        item.amount = amount; item.currency = currency; item.amount_is_custom = true
        audit.append({ actor: user, action: 'payment.amount_changed', entity: { type: 'payment', id: item.recurring_payment_id, title: item.title }, changes: [
          { field: 'due_date', label: 'Период со сроком', before: null, after: item.due_date },
          { field: 'amount', label: 'Сумма', before: `${oldAmount} ${oldCurrency}`, after: `${amount} ${currency}` },
          { field: 'currency', label: 'Валюта', before: oldCurrency, after: currency },
        ] })
      }
      return json(occurrenceView(item))
    }
    if (path.startsWith('/payment-occurrences/')) {
      queryAllowed(url.searchParams, [])
      const id = path.split('/').at(-1)!
      uuid(id)
      const item = db.occurrences.find(row => row.id === id) || fault(404, 'PAYMENT_OCCURRENCE_NOT_FOUND', 'Период не найден')
      if (method !== 'GET' && item.is_cancelled) fault(409, 'PAYMENT_CANCELLED', 'Период удалён и доступен только для просмотра')
      if (method === 'GET') return json(occurrenceView(item))
      if (method === 'PATCH') {
        const body = bodyObject(init, ['status', 'paid_on'], ['status', 'paid_on'])
        if (body.status !== 'paid' && body.status !== 'unpaid') invalid('status', 'Выберите paid или unpaid')
        if (body.status === 'unpaid') { if (body.paid_on !== null) invalid('paid_on', 'При отмене оплаты дата должна быть null') }
        else { const paidOn = date(body.paid_on, 'paid_on'); if (paidOn > DEMO_TODAY) invalid('paid_on', 'Фактическая дата не может быть позже сегодняшнего дня по МСК') }
        const oldStatus = item.status, oldPaidOn = item.paid_on
        item.status = body.status as 'paid' | 'unpaid'; item.paid_on = body.paid_on as string | null
        if (oldStatus !== item.status || oldPaidOn !== item.paid_on) audit.append({ actor: user,
          action: item.status === 'unpaid' ? 'payment.unpaid' : oldStatus === 'unpaid' ? 'payment.paid' : 'payment.date_changed',
          entity: { type: 'payment', id: item.recurring_payment_id, title: item.title }, changes: [
            { field: 'due_date', label: 'Период со сроком', before: null, after: item.due_date },
            { field: 'status', label: 'Статус', before: oldStatus === 'paid' ? 'Оплачено' : 'Не оплачено', after: item.status === 'paid' ? 'Оплачено' : 'Не оплачено' },
            { field: 'paid_on', label: 'Дата оплаты', before: oldPaidOn, after: item.paid_on },
          ] })
        return json(occurrenceView(item))
      }
    }
    if (path === '/recurring-payments') {
      if (method === 'GET') {
        queryAllowed(url.searchParams, ['limit', 'offset', 'is_active', 'periodicity', 'include_archived'])
        const active = booleanQuery(url.searchParams, 'is_active')
        return json(page(db.recurring.filter(item => (booleanQuery(url.searchParams, 'include_archived') || !item.is_archived) && (!url.searchParams.get('periodicity') || item.periodicity === url.searchParams.get('periodicity')) && (active === undefined || item.is_active === active)).sort((a, b) => b.created_at.localeCompare(a.created_at) || a.id.localeCompare(b.id)), url.searchParams))
      }
      if (method === 'POST') {
        requireAdmin(user); queryAllowed(url.searchParams, [])
        const body = bodyObject(init, ['title', 'amount', 'currency', 'first_due_date', 'periodicity'], ['title', 'amount', 'currency', 'first_due_date', 'periodicity'])
        if (typeof body.title !== 'string' || body.title.trim().length < 1 || Array.from(body.title.trim()).length > 200) invalid('title', 'Название должно содержать от 1 до 200 символов')
        const amount = money(body.amount), firstDue = date(body.first_due_date, 'first_due_date')
        if (typeof body.currency !== 'string' || !['RUB', 'USD', 'EUR'].includes(body.currency)) invalid('currency', 'Выберите RUB, USD или EUR')
        if (body.periodicity !== 'monthly') invalid('periodicity', 'Поддерживается ежемесячное повторение')
        const item: RecurringPayment = { id: crypto.randomUUID(), title: (body.title as string).trim(), amount, currency: body.currency as Currency, first_due_date: firstDue, next_due_date: firstDue, periodicity: 'monthly', anchor_day: Number(firstDue.slice(-2)), is_active: true, amount_effective_from: null, created_at: businessNowIso('mock') }
        addOccurrences(item); db.recurring.push(item)
        audit.append({ actor: user, action: 'payment.created', entity: { type: 'payment', id: item.id, title: item.title }, changes: [
          { field: 'amount', label: 'Сумма', before: null, after: `${item.amount} ${item.currency}` },
          { field: 'first_due_date', label: 'Первый срок', before: null, after: item.first_due_date },
        ] })
        return json(item, 201)
      }
    }
    if (/^\/recurring-payments\/[^/]+$/.test(path) && method === 'PATCH') {
      requireAdmin(user); queryAllowed(url.searchParams, [])
      const id = path.split('/')[2]; uuid(id)
      const body = bodyObject(init, ['title', 'amount', 'currency'], ['amount', 'currency'])
      const title = 'title' in body ? paymentTitle(body.title) : undefined
      const amount = exactAmount(BigInt(money(body.amount).replace('.', '')))
      if (typeof body.currency !== 'string' || !['RUB', 'USD', 'EUR'].includes(body.currency)) invalid('currency', 'Выберите RUB, USD или EUR')
      const currency = body.currency as Currency
      const payment = db.recurring.find(row => row.id === id) || fault(404, 'RECURRING_PAYMENT_NOT_FOUND', 'Регулярный платёж не найден')
      if (!payment.is_active || payment.periodicity !== 'monthly') fault(409, 'RECURRING_PAYMENT_STOPPED', 'Условия прекращённого платежа изменить нельзя')
      if (DEMO_TODAY.startsWith('9999-12')) fault(422, 'AMOUNT_EFFECTIVE_DATE_OUT_OF_RANGE', 'Следующий месяц выходит за поддерживаемый диапазон дат')
      const effective_from = calendarMonthDate(DEMO_TODAY, 1, 1)
      if (title !== undefined && title !== payment.title) {
        audit.append({ actor: user, action: 'payment.terms_changed', entity: { type: 'payment', id: payment.id, title }, changes: [{ field: 'title', label: 'Название', before: payment.title, after: title }] })
        payment.title = title
        for (const period of db.occurrences.filter(row => row.recurring_payment_id === payment.id)) period.title = title
      }
      if (payment.amount === amount && payment.currency === currency) return json({ payment, effective_from: payment.amount_effective_from || effective_from, updated_periods: 0, preserved_custom_periods: 0 })
      const future = db.occurrences.filter(item => item.recurring_payment_id === id && item.due_date >= effective_from && item.status === 'unpaid' && !item.is_cancelled)
      const preserved_custom_periods = future.filter(item => item.amount_is_custom).length
      const updated = future.filter(item => !item.amount_is_custom)
      const oldAmount = payment.amount, oldCurrency = payment.currency, oldEffective = payment.amount_effective_from
      for (const item of updated) { item.amount = amount; item.currency = currency }
      payment.amount = amount; payment.currency = currency; payment.amount_effective_from = effective_from
      audit.append({ actor: user, action: 'payment.terms_changed', entity: { type: 'payment', id: payment.id, title: payment.title }, changes: [
        { field: 'amount', label: 'Сумма в месяц', before: `${oldAmount} ${oldCurrency}`, after: `${amount} ${currency}` },
        { field: 'currency', label: 'Валюта', before: oldCurrency, after: currency },
        { field: 'amount_effective_from', label: 'Новые условия с', before: oldEffective, after: effective_from },
      ] })
      return json({ payment, effective_from, updated_periods: updated.length, preserved_custom_periods })
    }
    if (path.startsWith('/recurring-payments/') && method === 'DELETE') {
      requireAdmin(user); queryAllowed(url.searchParams, [])
      const id = path.split('/').at(-1)!; uuid(id)
      const item = db.recurring.find(row => row.id === id) || fault(404, 'RECURRING_PAYMENT_NOT_FOUND', 'Регулярный платёж не найден')
      if (item.is_active) audit.append({ actor: user, action: 'payment.stopped', entity: { type: 'payment', id: item.id, title: item.title },
        changes: [{ field: 'is_active', label: 'Регулярный платёж', before: 'Действует', after: 'Прекращён' }] })
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
        db.users.push(item); passwords.set(name, secret)
        audit.append({ actor: user, action: 'user.created', entity: { type: 'user', id: item.id, title: item.username },
          changes: [{ field: 'username', label: 'Логин', before: null, after: item.username }] })
        return json(item, 201)
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
        const oldName = item.username, oldSecret = passwords.get(item.username)
        passwords.delete(item.username); passwords.set(name, secret); item.username = name
        if (oldName !== name || oldSecret !== secret) audit.append({ actor: user, action: 'user.updated',
          entity: { type: 'user', id: item.id, title: item.username },
          changes: [{ field: 'username', label: 'Логин', before: oldName, after: name }] })
        return json(item)
      }
      if (method === 'DELETE') {
        db.users.splice(db.users.indexOf(item), 1); passwords.delete(item.username)
        audit.append({ actor: user, action: 'user.deleted', entity: { type: 'user', id: item.id, title: item.username },
          changes: [{ field: 'username', label: 'Логин', before: item.username, after: null }] })
        return new Response(null, { status: 204 })
      }
    }
    return fault(404, 'NOT_FOUND', 'Маршрут не найден')
  } catch (error) {
    if (error instanceof MockFault) return json({ error: { code: error.code, message: error.message, details: error.details } }, error.status, error.retryAfterSeconds)
    throw error
  }
}


