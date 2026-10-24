import { useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { ArrowRight, Eye, EyeOff, ShieldCheck } from './BrandIcons'
import { api, API_MODE, ApiError } from '../api/client'
import { DEMO_DATE_LABEL } from '../config/demo'
import type { AuthResponse } from '../types/api'
import { ErrorNotice } from './UI'
import { BrandMark } from './Brand'
import { ThemeControl } from './ThemeControl'

interface BrandLoginProps {
  onLogin: (session: AuthResponse) => void
  restoreError: unknown
  onRestore: () => void
}

function LoginPattern() {
  return <div className="aeza-login-pattern-panel" aria-hidden="true">
    <svg className="aeza-login-pattern" viewBox="0 0 640 900" preserveAspectRatio="none" fill="none" focusable="false">
      <path className="aeza-login-pattern-lines" d="M-24 120h92c34 0 50-16 50-50v-94M-24 138h110c34 0 50-16 50-50V-24M-24 156h128c34 0 50-16 50-50V-24M666 730H530c-34 0-50 16-50 50v144M666 748H548c-34 0-50 16-50 50v126M666 766H566c-34 0-50 16-50 50v108" strokeWidth="2" strokeLinecap="round" vectorEffect="non-scaling-stroke"/>
      <path className="aeza-login-pattern-accent" d="M352-30v120c0 42 22 64 64 64h254" strokeWidth="5" strokeLinecap="round" vectorEffect="non-scaling-stroke" pathLength="1"/>
      <path className="aeza-login-pattern-return" d="M670 280H584c-30 0-46 16-46 46v98c0 30-16 46-46 46h-30" strokeWidth="3" strokeLinecap="round" vectorEffect="non-scaling-stroke" pathLength="1"/>
      <path className="aeza-login-pattern-accent aeza-login-pattern-accent--bottom" d="M138 932v-98c0-40 20-60 60-60h150c40 0 60-20 60-60v-34" strokeWidth="4" strokeLinecap="round" vectorEffect="non-scaling-stroke" pathLength="1"/>
      <path className="aeza-login-pattern-return aeza-login-pattern-return--short" d="M-30 644h74c30 0 46-16 46-46v-84" strokeWidth="3" strokeLinecap="round" vectorEffect="non-scaling-stroke" pathLength="1"/>
      <path className="aeza-login-pattern-lines" d="M624 36H518c-22 0-34 12-34 34v20M54 862h64M670 564h-52c-26 0-40 14-40 40v32" strokeWidth="2" strokeLinecap="round" vectorEffect="non-scaling-stroke"/>
    </svg>
  </div>
}

export function BrandLogin({ onLogin, restoreError, onRestore }: BrandLoginProps) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [fields, setFields] = useState<Record<string, string>>({})
  const guard = useRef(false)

  function clearField(field: string) {
    setFields(current => ({ ...current, [field]: '' }))
    setError(null)
  }

  function chooseDemo(role: 'admin' | 'user') {
    setUsername(role === 'admin' ? 'admin' : 'ivan')
    setPassword(role === 'admin' ? 'Admin123!' : 'example-password-only')
    setError(null)
    setFields({})
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (guard.current) return
    guard.current = true
    setBusy(true)
    setError(null)
    setFields({})
    try {
      const data = await api.login({ username, password })
      setPassword('')
      onLogin(data)
    } catch (reason) {
      setError(reason)
      if (reason instanceof ApiError) setFields(Object.fromEntries(reason.details.map(item => [item.field, item.message])))
    } finally {
      guard.current = false
      setBusy(false)
    }
  }

  return <div className="aeza-login">
    <section className="aeza-login-story" aria-labelledby="aeza-login-story-title">
      <LoginPattern/>
      <div className="aeza-login-brand" aria-label="Aeza, Invoice Keeper">
        <BrandMark size={56}/>
        <span className="aeza-login-product">Invoice<span>Keeper</span></span>
      </div>
      <div className="aeza-login-story-copy">
        <p className="aeza-login-eyebrow"><span aria-hidden="true"/>Рабочее пространство команды</p>
        <h2 id="aeza-login-story-title">Всё по плану.<br/>Всё вовремя<span>.</span></h2>
        <p className="aeza-login-story-caption">Платежи, бюджет и история решений. Меньше рутины — больше ясности в каждом дне.</p>
        <div className="aeza-login-topics" aria-label="Возможности рабочего пространства"><span>Платежи</span><span>Бюджет</span><span>История</span></div>
      </div>
      <p className="aeza-login-story-footer">Чёткие сроки. Общая картина.</p>
    </section>
    <main className="aeza-login-main">
      <div className="aeza-login-theme"><ThemeControl/></div>
      <div className="aeza-login-form-card">
        <div className="aeza-login-form-heading">
          <p className="aeza-login-eyebrow">Добро пожаловать</p>
          <h1>Вход в систему</h1>
          <p>Войдите в свою учётную запись, чтобы продолжить работу с платежами команды.</p>
        </div>
        {restoreError ? <ErrorNotice error={restoreError} onRetry={onRestore}/> : null}
        {error ? <div className="aeza-login-error" role="alert">{error instanceof Error ? error.message : 'Не удалось войти. Попробуйте ещё раз.'}</div> : null}
        <form className="aeza-login-form" onSubmit={submit} aria-busy={busy}>
          <div className="aeza-login-field">
            <label htmlFor="login-username">Логин</label>
            <input id="login-username" name="username" autoComplete="username" autoCapitalize="none" spellCheck={false} value={username} onChange={event => { setUsername(event.target.value); clearField('username') }} required disabled={busy} aria-invalid={Boolean(fields.username)} aria-describedby={fields.username ? 'login-username-error' : undefined}/>
            {fields.username && <span className="aeza-login-field-error" id="login-username-error">{fields.username}</span>}
          </div>
          <div className="aeza-login-field">
            <label htmlFor="login-password">Пароль</label>
            <div className="aeza-login-password">
              <input id="login-password" name="password" type={showPassword ? 'text' : 'password'} autoComplete="current-password" value={password} onChange={event => { setPassword(event.target.value); clearField('password') }} required disabled={busy} aria-invalid={Boolean(fields.password)} aria-describedby={fields.password ? 'login-password-error' : undefined}/>
              <button type="button" className="aeza-login-password-toggle" disabled={busy} aria-label={showPassword ? 'Скрыть пароль' : 'Показать пароль'} aria-pressed={showPassword} onClick={() => setShowPassword(value => !value)}>{showPassword ? <EyeOff size={19} aria-hidden="true"/> : <Eye size={19} aria-hidden="true"/>}</button>
            </div>
            {fields.password && <span className="aeza-login-field-error" id="login-password-error">{fields.password}</span>}
          </div>
          <button className="aeza-login-submit" type="submit" disabled={busy}>{busy ? <><span className="spinner" aria-hidden="true"/>Входим…</> : <>Войти<ArrowRight size={19} aria-hidden="true"/></>}</button>
        </form>
        {API_MODE === 'mock' && <aside className="aeza-login-demo" aria-label="Демонстрация интерфейса">
          <div className="aeza-login-demo-title"><strong>Попробовать интерфейс</strong><span>Демо</span></div>
          <p>Выберите роль, затем нажмите «Войти».</p>
          <div className="aeza-login-demo-roles"><button type="button" disabled={busy} onClick={() => chooseDemo('admin')}>Администратор</button><button type="button" disabled={busy} onClick={() => chooseDemo('user')}>Пользователь</button></div>
          <p className="aeza-login-demo-date">Данные на {DEMO_DATE_LABEL}.</p>
        </aside>}
        <p className="aeza-login-security"><ShieldCheck size={16} aria-hidden="true"/>Доступ только для участников команды</p>
      </div>
    </main>
  </div>
}
