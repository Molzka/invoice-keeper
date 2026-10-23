import { useCallback, useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { Check, Eye, EyeOff, LayoutList, LogOut, Plus, ReceiptText, Repeat2, ShieldCheck, UserRound, Users, X } from 'lucide-react'
import { api, API_MODE, ApiError } from './api/client'
import type { User } from './types/api'
import { DEMO_TODAY } from './mocks/fixtures'
import { moscowToday, monthLabel } from './lib/format'
import { PaymentsView } from './components/PaymentsView'
import { RecurringView, UsersView } from './components/AdminViews'
import { ErrorNotice } from './components/UI'

type View = 'payments' | 'recurring' | 'history' | 'users'
function currentView(): View { const value = window.location.hash.slice(1); return ['payments','recurring','history','users'].includes(value) ? value as View : 'payments' }
function Brand({ onHome }: { onHome?: () => void }) {
  const [open, setOpen] = useState(false)
  return <button type="button" className="brand-logo" data-open={open} aria-label="Invoice Keeper — главная" onClick={() => { if (window.matchMedia('(hover: none)').matches && !open) setOpen(true); else onHome?.() }} onBlur={() => setOpen(false)}><span className="brand-letter" aria-hidden="true">é</span><span className="brand-name" aria-hidden="true">Invoice Keeper</span><span className="brand-receipt" aria-hidden="true"><ReceiptText size={15}/></span></button>
}

function Login({ onLogin, restoreError, onRestore }: { onLogin: (user: User) => void; restoreError: unknown; onRestore: () => void }) {
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
    try { const data = await api.login({ username, password }); setPassword(''); onLogin(data.user) }
    catch (reason) { setError(reason); if (reason instanceof ApiError) setFields(Object.fromEntries(reason.details.map(item => [item.field,item.message]))) }
    finally { guard.current = false; setBusy(false) }
  }
  return <div className="login-page"><section className="login-art" aria-label="Invoice Keeper"><Brand/><img src="/glass-calendar.png" alt=""/><div><p className="eyebrow">Invoice Keeper</p><h2>Платежи<br/>под контролем.</h2><p>Ближайшие сроки, история оплат и напоминания — всё в одном месте.</p></div></section><main className="login-card"><div className="login-brand"><Brand/></div><p className="eyebrow">Добро пожаловать</p><h1 className="login-heading">Вход в систему</h1><p className="login-caption">Войдите в свою учётную запись, чтобы управлять регулярными платежами.</p>{restoreError ? <ErrorNotice error={restoreError} onRetry={onRestore}/> : null}{error ? <div className="error-banner" role="alert">{error instanceof Error ? error.message : 'Не удалось войти'}</div> : null}<form onSubmit={submit}><div className="field"><label htmlFor="login-username">Логин</label><input id="login-username" name="username" autoComplete="username" value={username} onChange={event => setUsername(event.target.value)} required disabled={busy} aria-invalid={Boolean(fields.username)} aria-describedby={fields.username ? 'login-username-error' : undefined}/>{fields.username && <span className="field-error" id="login-username-error">{fields.username}</span>}</div><div className="field"><label htmlFor="login-password">Пароль</label><div className="password-field"><input id="login-password" name="password" type={showPassword ? 'text' : 'password'} autoComplete="current-password" value={password} onChange={event => setPassword(event.target.value)} required disabled={busy} aria-invalid={Boolean(fields.password)} aria-describedby={fields.password ? 'login-password-error' : undefined}/><button type="button" className="password-toggle" aria-label={showPassword ? 'Скрыть пароль' : 'Показать пароль'} aria-pressed={showPassword} onClick={() => setShowPassword(value => !value)}>{showPassword ? <EyeOff size={18}/> : <Eye size={18}/>}</button></div>{fields.password && <span className="field-error" id="login-password-error">{fields.password}</span>}</div><button className="btn btn-primary" type="submit" disabled={busy}>{busy && <span className="spinner"/>}{busy ? 'Входим…' : 'Войти'}</button></form>{API_MODE === 'mock' && <aside className="login-demo"><p><strong>Демонстрация интерфейса</strong></p><p>Выберите роль — данные для входа заполнятся автоматически.</p><button type="button" disabled={busy} onClick={() => { setUsername('admin'); setPassword('Admin123!'); setError(null) }}>Администратор</button><button type="button" disabled={busy} onClick={() => { setUsername('ivan'); setPassword('example-password-only'); setError(null) }}>Пользователь</button><p style={{ marginTop: 10 }}>Демо-данные по состоянию на 23 октября 2026.</p></aside>}<p className="login-status"><ShieldCheck size={15}/> Доступ только для участников команды</p></main></div>
}

export default function App() {
  const [user, setUser] = useState<User | null>(null)
  const [restoring, setRestoring] = useState(true)
  const [restoreError, setRestoreError] = useState<unknown>(null)
  const [view, setView] = useState<View>(currentView)
  const [revision, setRevision] = useState(0)
  const [toast, setToast] = useState('')
  const [logoutBusy, setLogoutBusy] = useState(false)
  const [historyRule, setHistoryRule] = useState<{id:string;title:string} | null>(null)
  const [createRequested, setCreateRequested] = useState(0)
  const userRef = useRef<User | null>(null)
  const logoutGuard = useRef(false)
  userRef.current = user
  const today = API_MODE === 'mock' ? DEMO_TODAY : moscowToday()
  const changed = useCallback(() => setRevision(value => value + 1), [])
  const notify = useCallback((message: string) => setToast(message), [])
  const createHandled = useCallback(() => setCreateRequested(0), [])
  const restore = useCallback(async () => {
    setRestoring(true); setRestoreError(null)
    try { const response = await api.me(); setUser(response.user) }
    catch (error) { setUser(null); if (!(error instanceof ApiError && error.status === 401)) setRestoreError(error) }
    finally { setRestoring(false) }
  }, [])
  useEffect(() => {
    void restore()
    const unauthorized = () => { if (userRef.current) setToast('Сессия завершилась. Войдите снова.'); setUser(null); setRestoring(false) }
    const hashChanged = () => setView(currentView())
    window.addEventListener('invoice:unauthorized', unauthorized)
    window.addEventListener('hashchange', hashChanged)
    return () => { window.removeEventListener('invoice:unauthorized', unauthorized); window.removeEventListener('hashchange', hashChanged) }
  }, [restore])
  useEffect(() => { if (!toast) return; const timer = setTimeout(() => setToast(''), 6500); return () => clearTimeout(timer) }, [toast])
  function navigate(next: View) { window.location.hash = next; setView(next) }
  function showHistory(id: string, title: string) { setHistoryRule({id,title}); navigate('history') }
  async function logout() {
    if (logoutGuard.current) return
    logoutGuard.current = true; setLogoutBusy(true)
    try { await api.logout(); setUser(null); setRestoreError(null); setToast('') }
    catch (error) { if (!(error instanceof ApiError && error.status === 401)) notify('Выход не подтверждён сервером. Проверьте соединение и повторите.'); else setUser(null) }
    finally { logoutGuard.current = false; setLogoutBusy(false) }
  }
  if (restoring) return <div className="empty-state" style={{ minHeight: '100vh' }} role="status"><Brand/><span className="spinner"/><p>Восстанавливаем вашу сессию…</p></div>
  if (!user) return <><Login onLogin={value => { setUser(value); setRestoreError(null); changed() }} restoreError={restoreError} onRestore={() => void restore()}/>{toast && <div className="toast" role="status">{toast}<button className="toast-close" aria-label="Скрыть сообщение" onClick={() => setToast('')}><X size={16}/></button></div>}</>
  const admin = user.role === 'admin'
  const titles: Record<View,string> = { payments:'Платежи', recurring:'Регулярные платежи', history:'История оплат', users:'Пользователи' }
  const subtitles: Record<View,string> = { payments:'Ближайшие сроки и обязательства команды — в одном месте.', recurring:'Настройте повторение один раз. История каждого периода сохранится.', history:'Каждый месяц — отдельный срок, статус и фактическая дата оплаты.', users:'Управляйте доступом обычных пользователей к общей панели.' }
  return <div className="app-shell"><a className="skip-link" href="#main-content" onClick={event => { event.preventDefault(); document.getElementById('main-content')?.focus(); }}>Перейти к содержимому</a><header className="topbar"><div className="brand-slot"><Brand onHome={() => navigate('payments')}/></div><nav className="main-nav" aria-label="Основная навигация">{([{id:'payments',text:'Платежи',icon:LayoutList},{id:'recurring',text:'Регулярные',icon:Repeat2},{id:'history',text:'История',icon:ReceiptText},...(admin ? [{id:'users',text:'Пользователи',icon:Users}] : [])]).map(item => <a key={item.id} className={`nav-link ${view === item.id ? 'active' : ''}`} href={`#${item.id}`} aria-current={view === item.id ? 'page' : undefined}><item.icon size={16} aria-hidden="true"/>{item.text}</a>)}</nav><div className="user-menu"><div className="user-avatar" aria-hidden="true"><UserRound size={18}/></div><div><strong>{user.username}</strong><small>{admin ? 'Администратор' : 'Пользователь'}</small></div><button className="icon-button" type="button" disabled={logoutBusy} onClick={() => void logout()} aria-label="Выйти из системы">{logoutBusy ? <span className="spinner"/> : <LogOut size={17}/>}</button></div></header><main id="main-content" className="app-main" tabIndex={-1}>{(view === 'payments' || view === 'history') && <div className="page-head"><div><p className="eyebrow">{view === 'payments' ? monthLabel(today.slice(0,7)) : 'Рабочее пространство'}{API_MODE === 'mock' && <span className="demo-badge">Демо</span>}</p><h1 className="page-title" tabIndex={-1}>{titles[view]}</h1><p className="page-subtitle">{subtitles[view]}</p></div>{view === 'payments' && <><img className="hero-art" src="/glass-calendar.png" alt=""/>{admin && <button className="btn btn-primary" type="button" onClick={() => { setCreateRequested(value => value + 1); navigate('recurring') }}><Plus size={18}/> Добавить платёж</button>}</>}</div>}{(view === 'payments' || view === 'history') && <PaymentsView key={`${view}:${view === 'history' ? historyRule?.id || 'all' : ''}`} mode={view} revision={revision} today={today} selectedRule={view === 'history' ? historyRule : null} onClearRule={() => setHistoryRule(null)} onHistory={showHistory} onChanged={changed} notify={notify}/>}{view === 'recurring' && <RecurringView isAdmin={admin} onChanged={changed} onHistory={showHistory} notify={notify} createRequested={createRequested} onCreateRequestHandled={createHandled}/>}{view === 'users' && <UsersView isAdmin={admin} onChanged={changed} onHistory={showHistory} notify={notify}/>}</main>{toast && <div className="toast" role="status"><Check size={17}/>{toast}<button className="toast-close" type="button" aria-label="Скрыть сообщение" onClick={() => setToast('')}><X size={16}/></button></div>}</div>
}
