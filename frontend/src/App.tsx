import { useCallback, useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { CalendarDays, ListChecks, Check, Eye, EyeOff, KeyRound, LayoutList, LogOut, Plus, ReceiptText, Repeat2, ShieldCheck, UserRound, Users, X } from 'lucide-react'
import { api, API_MODE, ApiError } from './api/client'
import type { AuthResponse, User } from './types/api'
import { businessToday, DEMO_DATE_LABEL } from './config/demo'
import { monthLabel } from './lib/format'
import { defaultPaymentFilters, paymentHash, viewHash } from './lib/payment-route'
import type { PaymentRoute, WorkspaceView } from './lib/payment-route'
import { useWorkspaceRoute, writeWorkspaceHash } from './lib/useWorkspaceRoute'
import { PageHeader } from './components/PageHeader'
import { SectionArt } from './components/SectionArt'
import { PaymentsView } from './components/PaymentsView'
import { PaymentCalendar } from './components/PaymentCalendar'
import { ActivityView } from './components/ActivityView'
import { RecurringView, UsersView } from './components/AdminViews'
import { ErrorNotice } from './components/UI'
import { ChangePasswordDrawer } from './components/ChangePasswordDrawer'

type View = WorkspaceView
function Brand({ onHome }: { onHome?: () => void }) {
  const [open, setOpen] = useState(false)
  return <button type="button" className="brand-logo" data-open={open} aria-label="Invoice Keeper — главная" onClick={() => { if (window.matchMedia('(hover: none)').matches && !open) setOpen(true); else onHome?.() }} onBlur={() => setOpen(false)}><span className="brand-letter" aria-hidden="true">é</span><span className="brand-name" aria-hidden="true"><span className="brand-word brand-word-invoice">Invoice</span><span className="brand-word brand-word-keeper">Keeper<span className="brand-name-dot">.</span></span></span><span className="brand-receipt" aria-hidden="true"><ReceiptText size={15}/></span></button>
}

function Login({ onLogin, restoreError, onRestore }: { onLogin: (session: AuthResponse) => void; restoreError: unknown; onRestore: () => void }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [fields, setFields] = useState<Record<string,string>>({})
  const guard = useRef(false)
  async function submit(event: FormEvent) {
    event.preventDefault()
    if (guard.current) return
    guard.current = true; setBusy(true); setError(null); setFields({})
    try { const data = await api.login({ username, password }); setPassword(''); onLogin(data) }
    catch (reason) { setError(reason); if (reason instanceof ApiError) setFields(Object.fromEntries(reason.details.map(item => [item.field,item.message]))) }
    finally { guard.current = false; setBusy(false) }
  }
  return <div className="login-page"><section className="login-art" aria-label="Invoice Keeper"><Brand/><SectionArt kind="login" className="login-scene"/><div><p className="eyebrow">Invoice Keeper</p><h2>Платежи<br/>под контролем.</h2><p>Ближайшие сроки, история оплат и напоминания — всё в одном месте.</p></div></section><main className="login-card"><div className="login-brand"><Brand/></div><p className="eyebrow">Добро пожаловать</p><h1 className="login-heading">Вход в систему</h1><p className="login-caption">Войдите в свою учётную запись, чтобы управлять регулярными платежами.</p>{restoreError ? <ErrorNotice error={restoreError} onRetry={onRestore}/> : null}{error ? <div className="error-banner" role="alert">{error instanceof Error ? error.message : 'Не удалось войти'}</div> : null}<form onSubmit={submit}><div className="field"><label htmlFor="login-username">Логин</label><input id="login-username" name="username" autoComplete="username" value={username} onChange={event => setUsername(event.target.value)} required disabled={busy} aria-invalid={Boolean(fields.username)} aria-describedby={fields.username ? 'login-username-error' : undefined}/>{fields.username && <span className="field-error" id="login-username-error">{fields.username}</span>}</div><div className="field"><label htmlFor="login-password">Пароль</label><div className="password-field"><input id="login-password" name="password" type={showPassword ? 'text' : 'password'} autoComplete="current-password" value={password} onChange={event => setPassword(event.target.value)} required disabled={busy} aria-invalid={Boolean(fields.password)} aria-describedby={fields.password ? 'login-password-error' : undefined}/><button type="button" className="password-toggle" aria-label={showPassword ? 'Скрыть пароль' : 'Показать пароль'} aria-pressed={showPassword} onClick={() => setShowPassword(value => !value)}>{showPassword ? <EyeOff size={18}/> : <Eye size={18}/>}</button></div>{fields.password && <span className="field-error" id="login-password-error">{fields.password}</span>}</div><button className="btn btn-primary" type="submit" disabled={busy}>{busy && <span className="spinner"/>}{busy ? 'Входим…' : 'Войти'}</button></form>{API_MODE === 'mock' && <aside className="login-demo"><p><strong>Демонстрация интерфейса</strong></p><p>Выберите роль — данные для входа заполнятся автоматически.</p><button type="button" disabled={busy} onClick={() => { setUsername('admin'); setPassword('Admin123!'); setError(null) }}>Администратор</button><button type="button" disabled={busy} onClick={() => { setUsername('ivan'); setPassword('example-password-only'); setError(null) }}>Пользователь</button><p style={{ marginTop: 10 }}>Демо-данные по состоянию на {DEMO_DATE_LABEL}.</p></aside>}<p className="login-status"><ShieldCheck size={15}/> Доступ только для участников команды</p></main></div>
}

export default function App() {
  const [session, setSession] = useState<AuthResponse | null>(null)
  const user = session?.user ?? null
  const [clockNow, setClockNow] = useState(Date.now)
  const [restoring, setRestoring] = useState(true)
  const [restoreError, setRestoreError] = useState<unknown>(null)
  const [revision, setRevision] = useState(0)
  const [toast, setToast] = useState('')
  const [logoutBusy, setLogoutBusy] = useState(false)
  const [passwordOpen, setPasswordOpen] = useState(false)
  const [passwordLimit, setPasswordLimit] = useState({ userId: '', retryAt: 0 })
  const passwordOpenRef = useRef(false)
  passwordOpenRef.current = passwordOpen
  const [historyRule, setHistoryRule] = useState<{id:string;title:string} | null>(null)
  const [createRequested, setCreateRequested] = useState(0)
  const userRef = useRef<User | null>(null)
  const logoutGuard = useRef(false)
  userRef.current = user
  const today = session ? businessToday(API_MODE, new Date(clockNow), session.timezone) : null
  const route = useWorkspaceRoute(today)
  const view = route?.view ?? 'payments'
  const selectedRule = view === 'history' && route?.ruleId
    ? { id: route.ruleId, title: historyRule?.id === route.ruleId ? historyRule.title : 'История выбранного платежа' }
    : null
  const changePaymentRoute = useCallback((next: PaymentRoute, replace = false) => {
    writeWorkspaceHash(paymentHash(next.view === 'history' ? 'history' : 'payments', next.filters, { limit: next.limit, offset: next.offset, ruleId: next.ruleId }), replace)
  }, [])
  const changed = useCallback(() => setRevision(value => value + 1), [])
  const notify = useCallback((message: string) => setToast(message), [])
  const createHandled = useCallback(() => setCreateRequested(0), [])
  const restore = useCallback(async () => {
    setRestoring(true); setRestoreError(null)
    try { const response = await api.me(); setSession(response) }
    catch (error) { setSession(null); if (!(error instanceof ApiError && error.status === 401)) setRestoreError(error) }
    finally { setRestoring(false) }
  }, [])
  useEffect(() => {
    void restore()
    const unauthorized = (event: Event) => {
      const message = (event as CustomEvent<{ message?: string }>).detail?.message
      if (message) setToast(message)
      else if (userRef.current) setToast(passwordOpenRef.current ? 'Сессия завершилась. Войдите снова. Если вы меняли пароль, попробуйте новый.' : 'Сессия завершилась. Войдите снова.')
      setPasswordOpen(false); setPasswordLimit({ userId: '', retryAt: 0 }); setHistoryRule(null)
      setSession(null); setRestoreError(null); setRestoring(false)
    }
    const sessionUpdated = (event: Event) => {
      const data = (event as CustomEvent<AuthResponse>).detail
      if (userRef.current?.id === data.user.id && userRef.current.role === data.user.role) setSession(data)
    }
    window.addEventListener('invoice:unauthorized', unauthorized)
    window.addEventListener('invoice:session', sessionUpdated)
    return () => { window.removeEventListener('invoice:unauthorized', unauthorized); window.removeEventListener('invoice:session', sessionUpdated) }
  }, [restore])
  useEffect(() => {
    const tick = () => setClockNow(Date.now())
    const timer = setInterval(tick, 30000)
    window.addEventListener('focus', tick)
    return () => { clearInterval(timer); window.removeEventListener('focus', tick) }
  }, [])
  useEffect(() => { if (!toast) return; const timer = setTimeout(() => setToast(''), 6500); return () => clearTimeout(timer) }, [toast])
  function navigate(next: View) { writeWorkspaceHash(viewHash(next)) }
  function showHistory(id: string, title: string) {
    if (!route || !today) return
    setHistoryRule({ id, title })
    writeWorkspaceHash(paymentHash('history', defaultPaymentFilters('history', today), { limit: route.limit, offset: 0, ruleId: id }))
  }
  async function logout() {
    if (logoutGuard.current) return
    logoutGuard.current = true; setLogoutBusy(true)
    try { await api.logout(); setPasswordOpen(false); setSession(null); setRestoreError(null); setToast('') }
    catch (error) {
      if (error instanceof ApiError && error.status === 401) setSession(null)
      else if (error instanceof ApiError && error.code === 'CSRF_RECOVERED') notify('Сессия обновлена. Чтобы выйти, нажмите «Выйти» ещё раз.')
      else if (error instanceof ApiError && error.code === 'CSRF_REFRESH_FAILED') notify(error.message)
      else notify('Выход не подтверждён сервером. Проверьте соединение и повторите.')
    }
    finally { logoutGuard.current = false; setLogoutBusy(false) }
  }
  if (restoring) return <div className="empty-state" style={{ minHeight: '100vh' }} role="status"><Brand/><span className="spinner"/><p>Восстанавливаем вашу сессию…</p></div>
  if (!user || !session || !route || !today) return <><Login onLogin={value => { setPasswordOpen(false); setSession(value); setRestoreError(null); changed() }} restoreError={restoreError} onRestore={() => void restore()}/>{toast && <div className="toast" role="status">{toast}<button className="toast-close" aria-label="Скрыть сообщение" onClick={() => setToast('')}><X size={16}/></button></div>}</>
  const admin = user.role === 'admin'
  const titles: Record<View,string> = { payments:'Платежи', recurring:'Регулярные платежи', history:'История оплат', users:'Пользователи', calendar:'Календарь оплат', activity:'Журнал действий' }
  const subtitles: Record<View,string> = { payments:'Ближайшие сроки и обязательства команды — в одном месте.', recurring:'Настройте повторение один раз. История каждого периода сохранится.', history:'Каждый месяц — отдельный срок, статус и фактическая дата оплаты.', users:'Управляйте доступом обычных пользователей к общей панели.', calendar:'Сроки платежей на одном календаре.', activity:'История изменений в рабочем пространстве.' }
  return <div className="app-shell"><a className="skip-link" href="#main-content" onClick={event => { event.preventDefault(); document.getElementById('main-content')?.focus(); }}>Перейти к содержимому</a><header className="topbar"><div className="brand-slot"><Brand onHome={() => navigate('payments')}/></div><nav className="main-nav" aria-label="Основная навигация">{([{id:'payments',text:'Платежи',icon:LayoutList},{id:'calendar',text:'Календарь',icon:CalendarDays},{id:'recurring',text:'Регулярные',icon:Repeat2},{id:'history',text:'История',icon:ReceiptText},...(admin ? [{id:'activity',text:'Журнал',icon:ListChecks},{id:'users',text:'Пользователи',icon:Users}] : [])]).map(item => <a key={item.id} className={`nav-link ${view === item.id ? 'active' : ''}`} href={item.id === view ? window.location.hash || viewHash(view) : `#${item.id}`} aria-current={view === item.id ? 'page' : undefined}><item.icon size={16} aria-hidden="true"/>{item.text}</a>)}</nav><div className="user-menu">{admin ? <div className="account-identity" role="group" aria-label={`${user.username}, администратор`}><span className="user-avatar" aria-hidden="true"><UserRound size={18}/></span><span className="account-copy"><strong>{user.username}</strong><small>Администратор</small></span></div> : <button className="account-button" type="button" aria-label="Сменить пароль" title="Сменить пароль" disabled={logoutBusy} onClick={() => setPasswordOpen(true)}><span className="user-avatar" aria-hidden="true"><UserRound size={18}/><span className="account-key"><KeyRound size={11}/></span></span><span className="account-copy"><strong>{user.username}</strong><small>Пользователь</small></span></button>}<button className="icon-button" type="button" disabled={logoutBusy} onClick={() => void logout()} aria-label="Выйти из системы">{logoutBusy ? <span className="spinner"/> : <LogOut size={17}/>}</button></div></header><main id="main-content" className="app-main" tabIndex={-1}>{(view === 'payments' || view === 'history') && <PageHeader key={view} kind={view} title={titles[view]} description={subtitles[view]} eyebrow={<>{view === 'payments' ? (route.filters.date_from.slice(0,7) === route.filters.date_to.slice(0,7) ? monthLabel(route.filters.date_from.slice(0,7)) : 'Выбранный период') : 'Рабочее пространство'}{API_MODE === 'mock' && <span className="demo-badge">Демо</span>}</>}>{view === 'payments' && admin && <button className="btn btn-primary" type="button" onClick={() => { setCreateRequested(value => value + 1); navigate('recurring') }}><Plus size={18}/> Добавить платёж</button>}</PageHeader>}{(view === 'payments' || view === 'history') && <PaymentsView key={`${view}:${route.ruleId || 'all'}`} mode={view} route={route} onRouteChange={changePaymentRoute} revision={revision} today={today} timezone={session.timezone} selectedRule={selectedRule} onHistory={showHistory} onChanged={changed} notify={notify}/>}{view === 'calendar' && <PaymentCalendar today={today} timezone={session.timezone} revision={revision} onChanged={changed} notify={notify} onHistory={showHistory}/>}{view === 'activity' && <ActivityView isAdmin={admin} revision={revision} today={today} timezone={session.timezone} onHistory={showHistory}/>}{view === 'recurring' && <RecurringView isAdmin={admin} today={today} timezone={session.timezone} onChanged={changed} onHistory={showHistory} notify={notify} createRequested={createRequested} onCreateRequestHandled={createHandled}/>}{view === 'users' && <UsersView isAdmin={admin} today={today} timezone={session.timezone} onChanged={changed} onHistory={showHistory} notify={notify}/>}</main>{passwordOpen && !admin && <ChangePasswordDrawer key={user.id} user={user} retryAt={passwordLimit.userId === user.id ? passwordLimit.retryAt : 0} onRateLimit={retryAt => setPasswordLimit({ userId: user.id, retryAt })} onSessionUpdated={value => { if (userRef.current?.id === value.user.id) setSession(value) }} onClose={() => setPasswordOpen(false)} onSaved={() => { setPasswordOpen(false); notify('Пароль изменён. Остальные сессии завершены.') }} onSignIn={message => { setPasswordOpen(false); setSession(null); setRestoreError(null); setToast(message) }}/>}{toast && <div className="toast" role="status"><Check size={17}/>{toast}<button className="toast-close" type="button" aria-label="Скрыть сообщение" onClick={() => setToast('')}><X size={16}/></button></div>}</div>
}
