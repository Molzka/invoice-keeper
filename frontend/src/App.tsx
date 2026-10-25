import { useCallback, useEffect, useRef, useState } from 'react'
import {
  CalendarDays,
  ListChecks,
  Check,
  KeyRound,
  LayoutList,
  LogOut,
  Plus,
  ReceiptText,
  Repeat2,
  ShieldCheck,
  UserRound,
  Users,
  X,
} from './components/BrandIcons'
import { BudgetView } from './components/BudgetView'
import { ReceiptsView } from './components/ReceiptsView'
import { OneTimePaymentDrawer } from './components/OneTimePaymentDrawer'
import { api, API_MODE, ApiError } from './api/client'
import type { AuthResponse, User } from './types/api'
import { businessToday } from './config/demo'
import { monthLabel } from './lib/format'
import { defaultPaymentFilters, paymentHash, viewHash } from './lib/payment-route'
import type { PaymentRoute, WorkspaceView } from './lib/payment-route'
import { useWorkspaceRoute, writeWorkspaceHash } from './lib/useWorkspaceRoute'
import { PageHeader } from './components/PageHeader'
import { Brand } from './components/Brand'
import { ThemeControl } from './components/ThemeControl'
import { SelectField } from './components/SelectField'
import { Access } from './components/Access'
import { SecurityDrawer } from './components/SecurityDrawer'
import { PaymentsView } from './components/PaymentsView'
import { PaymentCalendar } from './components/PaymentCalendar'
import { ActivityView } from './components/ActivityView'
import { RecurringView, UsersView } from './components/AdminViews'
import { ChangePasswordDrawer } from './components/ChangePasswordDrawer'

type View = WorkspaceView
export default function App() {
  const [session, setSession] = useState<AuthResponse | null>(null)
  const user = session?.user ?? null
  const [clockNow, setClockNow] = useState(Date.now)
  const [restoring, setRestoring] = useState(true)
  const [restoreError, setRestoreError] = useState<unknown>(null)
  const [revision, setRevision] = useState(0)
  const [toast, setToast] = useState('')
  const [logoutBusy, setLogoutBusy] = useState(false)
  const [creatingOnce, setCreatingOnce] = useState(false)
  const [passwordOpen, setPasswordOpen] = useState(false)
  const [securityOpen, setSecurityOpen] = useState(false)
  const [securityOffer, setSecurityOffer] = useState(false)
  const [passwordLimit, setPasswordLimit] = useState({ userId: '', retryAt: 0 })
  const passwordOpenRef = useRef(false)
  passwordOpenRef.current = passwordOpen
  const [historyRule, setHistoryRule] = useState<{ id: string; title: string } | null>(null)
  const userRef = useRef<User | null>(null)
  const logoutGuard = useRef(false)
  const logoutChannel = useRef<BroadcastChannel | null>(null)
  userRef.current = user
  const today = session ? businessToday(API_MODE, new Date(clockNow), session.timezone) : null
  const route = useWorkspaceRoute(today)
  const view = route?.view ?? 'payments'
  const selectedRule =
    view === 'history' && route?.ruleId
      ? { id: route.ruleId, title: historyRule?.id === route.ruleId ? historyRule.title : 'История выбранного платежа' }
      : null
  const changePaymentRoute = useCallback((next: PaymentRoute, replace = false) => {
    writeWorkspaceHash(
      paymentHash(next.view === 'history' ? 'history' : 'payments', next.filters, { limit: next.limit, offset: next.offset, ruleId: next.ruleId }),
      replace,
    )
  }, [])
  const changed = useCallback(() => setRevision((value) => value + 1), [])
  const notify = useCallback((message: string) => setToast(message), [])
  const restore = useCallback(async () => {
    setRestoring(true)
    setRestoreError(null)
    try {
      const response = await api.me()
      setSession(response)
    } catch (error) {
      setSession(null)
      if (!(error instanceof ApiError && error.status === 401)) setRestoreError(error)
    } finally {
      setRestoring(false)
    }
  }, [])
  useEffect(() => {
    const channel = API_MODE === 'real' ? new BroadcastChannel('invoice-keeper-auth') : null
    logoutChannel.current = channel
    if (channel)
      channel.onmessage = ({ data }) => {
        // Reload cancels old requests and discards private state in every open tab.
        if (data === 'logout') window.location.reload()
      }
    void restore()
    const unauthorized = (event: Event) => {
      const message = (event as CustomEvent<{ message?: string }>).detail?.message
      if (message) setToast(message)
      else if (userRef.current)
        setToast(passwordOpenRef.current ? 'Сессия завершилась. Войдите снова. Если вы меняли пароль, попробуйте новый.' : 'Сессия завершилась. Войдите снова.')
      setCreatingOnce(false)
      setPasswordOpen(false)
      setSecurityOpen(false)
      setSecurityOffer(false)
      setPasswordLimit({ userId: '', retryAt: 0 })
      setHistoryRule(null)
      setSession(null)
      setRestoreError(null)
      setRestoring(false)
    }
    const sessionUpdated = (event: Event) => {
      const data = (event as CustomEvent<AuthResponse>).detail
      if (userRef.current?.id === data.user.id && userRef.current.role === data.user.role) setSession(data)
    }
    window.addEventListener('invoice:unauthorized', unauthorized)
    window.addEventListener('invoice:session', sessionUpdated)
    return () => {
      channel?.close()
      logoutChannel.current = null
      window.removeEventListener('invoice:unauthorized', unauthorized)
      window.removeEventListener('invoice:session', sessionUpdated)
    }
  }, [restore])
  useEffect(() => {
    const tick = () => setClockNow(Date.now())
    const timer = setInterval(tick, 30000)
    window.addEventListener('focus', tick)
    return () => {
      clearInterval(timer)
      window.removeEventListener('focus', tick)
    }
  }, [])
  useEffect(() => {
    if (!toast) return
    const timer = setTimeout(() => setToast(''), 6500)
    return () => clearTimeout(timer)
  }, [toast])
  function navigate(next: View) {
    writeWorkspaceHash(viewHash(next))
  }
  function showHistory(id: string, title: string) {
    if (!route || !today) return
    setHistoryRule({ id, title })
    writeWorkspaceHash(paymentHash('history', defaultPaymentFilters('history', today), { limit: route.limit, offset: 0, ruleId: id }))
  }
  async function logout() {
    if (logoutGuard.current) return
    logoutGuard.current = true
    setLogoutBusy(true)
    try {
      await api.logout()
      logoutChannel.current?.postMessage('logout')
      setSecurityOpen(false)
      setSecurityOffer(false)
      setPasswordOpen(false)
      setSession(null)
      setRestoreError(null)
      setToast('')
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) setSession(null)
      else if (error instanceof ApiError && error.code === 'CSRF_RECOVERED') notify('Сессия обновлена. Чтобы выйти, нажмите «Выйти» ещё раз.')
      else if (error instanceof ApiError && error.code === 'CSRF_REFRESH_FAILED') notify(error.message)
      else notify('Выход не подтверждён сервером. Проверьте соединение и повторите.')
    } finally {
      logoutGuard.current = false
      setLogoutBusy(false)
    }
  }
  if (restoring)
    return (
      <div className="empty-state" style={{ minHeight: '100vh' }} role="status">
        <Brand />
        <span className="spinner" />
        <p>Восстанавливаем вашу сессию…</p>
      </div>
    )
  if (!user || !session || !route || !today)
    return (
      <>
        <Access
          onLogin={(value) => {
            setSecurityOpen(false)
            setSecurityOffer(false)
            setPasswordOpen(false)
            setSession(value)
            setRestoreError(null)
            setToast('')
            changed()
            if (value.user.role === 'user' && API_MODE === 'real')
              void api
                .security()
                .then((status) => {
                  if (userRef.current?.id === value.user.id && !status.mfa_enabled) setSecurityOffer(true)
                })
                .catch(() => {})
          }}
          restoreError={restoreError}
          onRestore={() => void restore()}
        />
        {toast && (
          <div className="toast" role="status">
            {toast}
            <button className="toast-close" aria-label="Скрыть сообщение" onClick={() => setToast('')}>
              <X size={16} />
            </button>
          </div>
        )}
      </>
    )
  const admin = user.role === 'admin'
  const allOverdue = view === 'history' && route.filters.tab === 'overdue' && !route.filters.date_from && !route.filters.date_to && !route.filters.currency && !route.filters.include_cancelled && !route.ruleId
  const navigation: { id: View; text: string; icon: typeof LayoutList }[] = [
    { id: 'payments', text: 'Платежи', icon: LayoutList },
    { id: 'calendar', text: 'Календарь', icon: CalendarDays },
    { id: 'recurring', text: 'Регулярные', icon: Repeat2 },
    { id: 'history', text: 'История', icon: ReceiptText },
    { id: 'budget', text: 'Бюджет', icon: ListChecks },
    { id: 'receipts', text: 'Чеки', icon: ReceiptText },
  ]
  if (admin) navigation.push({ id: 'activity', text: 'Журнал', icon: ListChecks }, { id: 'users', text: 'Пользователи', icon: Users })
  const titles: Record<View, string> = {
    payments: 'Платежи',
    recurring: 'Регулярные платежи',
    history: allOverdue ? 'Все просрочки' : 'История оплат',
    users: 'Пользователи',
    calendar: 'Календарь оплат',
    activity: 'Журнал действий',
    budget: 'Бюджет',
    receipts: 'Чеки и ссылки',
  }
  const subtitles: Record<View, string> = {
    payments: 'Ближайшие сроки и обязательства команды — в одном месте.',
    recurring: 'Настройте повторение один раз. История каждого периода сохранится.',
    history: allOverdue ? 'Неоплаченные периоды за всё время, включая прошлые месяцы.' : 'Каждый месяц — отдельный срок, статус и фактическая дата оплаты.',
    users: 'Управляйте доступом обычных пользователей к общей панели.',
    calendar: 'Сроки платежей на одном календаре.',
    activity: 'История изменений в рабочем пространстве.',
    budget: 'Бюджет месяца и года',
    receipts: 'Подтверждения оплаты',
  }
  return (
    <div className="app-shell">
      <a
        className="skip-link"
        href="#main-content"
        onClick={(event) => {
          event.preventDefault()
          document.getElementById('main-content')?.focus()
        }}
      >
        Перейти к содержимому
      </a>
      <header className="topbar">
        <div className="brand-slot">
          <Brand onHome={() => navigate('payments')} />
        </div>
        <nav className="main-nav" aria-label="Основная навигация">
          {navigation.map((item) => (
            <a
              key={item.id}
              className={`nav-link ${view === item.id ? 'active' : ''}`}
              href={item.id === view ? window.location.hash || viewHash(view) : `#${item.id}`}
              aria-current={view === item.id ? 'page' : undefined}
            >
              <item.icon size={16} aria-hidden="true" />
              {item.text}
            </a>
          ))}
        </nav>
        <nav className="mobile-nav" aria-label="Основная навигация">
          <label htmlFor="workspace-section">Раздел</label>
          <SelectField id="workspace-section" aria-label="Раздел приложения" value={view}
            options={navigation.map(item => ({ value: item.id, label: item.text }))}
            onChange={value => { const next = navigation.find(item => item.id === value); if (next && next.id !== view) navigate(next.id) }}/>
        </nav>
        <div className="user-menu">
          <ThemeControl />
          {!admin && (
            <button
              className="icon-button"
              type="button"
              aria-label="Безопасность"
              title="Безопасность"
              disabled={logoutBusy}
              onClick={() => {
                setSecurityOpen(true)
                setSecurityOffer(false)
              }}
            >
              <ShieldCheck size={18} />
            </button>
          )}
          {admin ? (
            <div className="account-identity" role="group" aria-label={`${user.username}, администратор`}>
              <span className="user-avatar" aria-hidden="true">
                <UserRound size={18} />
              </span>
              <span className="account-copy">
                <strong>{user.username}</strong>
                <small>Администратор</small>
              </span>
            </div>
          ) : (
            <button
              className="account-button"
              type="button"
              aria-label="Сменить пароль"
              title="Сменить пароль"
              disabled={logoutBusy}
              onClick={() => setPasswordOpen(true)}
            >
              <span className="user-avatar" aria-hidden="true">
                <UserRound size={18} />
                <span className="account-key">
                  <KeyRound size={11} />
                </span>
              </span>
              <span className="account-copy">
                <strong>{user.username}</strong>
                <small>Пользователь</small>
              </span>
            </button>
          )}
          <button className="icon-button" type="button" disabled={logoutBusy} onClick={() => void logout()} aria-label="Выйти из системы">
            {logoutBusy ? <span className="spinner" /> : <LogOut size={17} />}
          </button>
        </div>
      </header>
      <main id="main-content" className="app-main" tabIndex={-1}>
        {securityOffer && !admin && (
          <aside className="security-offer">
            <div>
              <strong>Защитите вход дополнительным кодом</strong>
              <p>Подключение добровольное — все функции уже доступны.</p>
            </div>
            <button
              className="btn btn-secondary btn-small"
              onClick={() => {
                setSecurityOpen(true)
                setSecurityOffer(false)
              }}
            >
              Настроить защиту
            </button>
            <button className="text-button" onClick={() => setSecurityOffer(false)}>
              Не сейчас
            </button>
          </aside>
        )}
        {(view === 'payments' || view === 'history') && (
          <PageHeader
            key={view}
            kind={view}
            title={titles[view]}
            description={subtitles[view]}
            eyebrow={
              <>
                {view === 'payments'
                  ? route.filters.date_from.slice(0, 7) === route.filters.date_to.slice(0, 7)
                    ? monthLabel(route.filters.date_from.slice(0, 7))
                    : 'Выбранный период'
                  : 'Рабочее пространство'}
                {API_MODE === 'mock' && <span className="demo-badge">Демо</span>}
              </>
            }
          >
            {view === 'payments' && admin && (
              <button className="btn btn-primary" type="button" onClick={() => setCreatingOnce(true)}>
                <Plus size={18} /> Добавить платёж
              </button>
            )}
          </PageHeader>
        )}
        {(view === 'payments' || view === 'history') && (
          <PaymentsView
            isAdmin={admin}
            key={`${view}:${route.ruleId || 'all'}`}
            mode={view}
            route={route}
            onRouteChange={changePaymentRoute}
            revision={revision}
            today={today}
            timezone={session.timezone}
            selectedRule={selectedRule}
            onHistory={showHistory}
            onChanged={changed}
            notify={notify}
          />
        )}
        {view === 'budget' && <BudgetView today={today} revision={revision} />}{' '}
        {view === 'receipts' && <ReceiptsView today={today} timezone={session.timezone} revision={revision} onChanged={changed} onHistory={showHistory} />}{' '}
        {view === 'calendar' && (
          <PaymentCalendar
            isAdmin={admin}
            today={today}
            timezone={session.timezone}
            revision={revision}
            onChanged={changed}
            notify={notify}
            onHistory={showHistory}
          />
        )}
        {view === 'activity' && <ActivityView isAdmin={admin} revision={revision} today={today} timezone={session.timezone} onHistory={showHistory} />}
        {view === 'recurring' && (
          <RecurringView isAdmin={admin} today={today} timezone={session.timezone} onChanged={changed} onHistory={showHistory} notify={notify} />
        )}
        {view === 'users' && (
          <UsersView isAdmin={admin} today={today} timezone={session.timezone} onChanged={changed} onHistory={showHistory} notify={notify} />
        )}
      </main>
      {securityOpen && !admin && (
        <SecurityDrawer
          key={user.id}
          user={user}
          onClose={() => setSecurityOpen(false)}
          onPassword={() => {
            setSecurityOpen(false)
            setPasswordOpen(true)
          }}
          onChanged={changed}
        />
      )}
      {creatingOnce && (
        <OneTimePaymentDrawer
          today={today}
          onClose={() => {
            setCreatingOnce(false)
            changed()
          }}
          onCreated={() => {
            setCreatingOnce(false)
            changed()
            notify('Разовый платёж добавлен.')
          }}
        />
      )}{' '}
      {passwordOpen && !admin && (
        <ChangePasswordDrawer
          key={user.id}
          user={user}
          retryAt={passwordLimit.userId === user.id ? passwordLimit.retryAt : 0}
          onRateLimit={(retryAt) => setPasswordLimit({ userId: user.id, retryAt })}
          onSessionUpdated={(value) => {
            if (userRef.current?.id === value.user.id) setSession(value)
          }}
          onClose={() => setPasswordOpen(false)}
          onSaved={() => {
            setPasswordOpen(false)
            changed()
            notify('Пароль изменён. Остальные сессии завершены.')
          }}
          onSignIn={(message) => {
            setPasswordOpen(false)
            setSession(null)
            setRestoreError(null)
            setToast(message)
          }}
        />
      )}
      {toast && (
        <div className="toast" role="status">
          <Check size={17} />
          {toast}
          <button className="toast-close" type="button" aria-label="Скрыть сообщение" onClick={() => setToast('')}>
            <X size={16} />
          </button>
        </div>
      )}
    </div>
  )
}
