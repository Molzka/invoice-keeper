import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { AlertCircle, Check, Eye, EyeOff, KeyRound, ShieldCheck } from './BrandIcons'
import { api, ApiError } from '../api/client'
import type { AuthResponse, User } from '../types/api'
import { validatePasswordFields } from '../lib/password-fields'
import type { PasswordErrors, PasswordField, PasswordFields } from '../lib/password-fields'
import { Drawer } from './UI'

type Props = {
  user: User
  retryAt: number
  onRateLimit: (deadline: number) => void
  onSessionUpdated: (session: AuthResponse) => void
  onClose: () => void
  onSaved: () => void
  onSignIn: (message: string) => void
}
type Recovery = 'none' | 'csrf-unverified' | 'uncertain-unverified' | 'uncertain-restored'
const emptyFields = (): PasswordFields => ({ current_password: '', new_password: '', confirm_password: '' })
const definitions: { key: PasswordField; label: string; autoComplete: string; hint?: string }[] = [
  { key: 'current_password', label: 'Текущий пароль', autoComplete: 'current-password' },
  { key: 'new_password', label: 'Новый пароль', autoComplete: 'new-password', hint: 'От 8 до 128 символов. Пароль должен отличаться от текущего.' },
  { key: 'confirm_password', label: 'Повторите новый пароль', autoComplete: 'new-password' },
]

export function ChangePasswordDrawer({ user, retryAt, onRateLimit, onSessionUpdated, onClose, onSaved, onSignIn }: Props) {
  const [values, setValues] = useState<PasswordFields>(emptyFields)
  const [shown, setShown] = useState<Partial<Record<PasswordField, boolean>>>({})
  const [fields, setFields] = useState<PasswordErrors>({})
  const [error, setError] = useState('')
  const [info, setInfo] = useState('')
  const [busy, setBusy] = useState(false)
  const [checking, setChecking] = useState(false)
  const [recovery, setRecovery] = useState<Recovery>('none')
  const [now, setNow] = useState(Date.now)
  const guard = useRef(false)
  const mounted = useRef(false)
  const inputs = useRef<Partial<Record<PasswordField, HTMLInputElement>>>({})
  const seconds = Math.max(0, Math.ceil((retryAt - now) / 1000))
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  useEffect(() => {
    if (!retryAt) return
    const timer = setInterval(() => { const time = Date.now(); setNow(time); if (time >= retryAt) clearInterval(timer) }, 500)
    return () => clearInterval(timer)
  }, [retryAt])
  function showFields(next: PasswordErrors) {
    setFields(next)
    const key = definitions.find(item => next[item.key])?.key
    if (key) requestAnimationFrame(() => { if (mounted.current) inputs.current[key]?.focus() })
  }
  function clearPasswords() { setValues(emptyFields()); setShown({}); setFields({}) }
  async function checkSession(uncertain: boolean) {
    setChecking(true)
    try {
      const data = await api.me()
      if (!mounted.current) return
      if (data.user.id !== user.id || data.user.role !== user.role) { clearPasswords(); onSignIn('Аккаунт изменился в другой вкладке. Войдите снова.'); return }
      onSessionUpdated(data)
      if (uncertain) { setRecovery('uncertain-restored'); setInfo('Сессия действует. Это не подтверждает, что пароль изменён.') }
      else { setRecovery('none'); setInfo('Сессия обновлена. Заполните форму ещё раз.'); setError('') }
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 401) {
        if (mounted.current) onSignIn(uncertain ? 'Попробуйте войти с новым паролем. Если он не подходит, используйте прежний.' : 'Сессия завершилась. Войдите снова.')
        return
      }
      if (mounted.current) {
        setRecovery(uncertain ? 'uncertain-unverified' : 'csrf-unverified')
        setInfo('Не удалось проверить сессию. Проверьте соединение и повторите проверку.')
      }
    } finally { if (mounted.current) setChecking(false) }
  }
  async function submit(event: FormEvent) {
    event.preventDefault()
    if (user.role !== 'user' || guard.current || retryAt > Date.now() || recovery !== 'none') return
    const nextFields = validatePasswordFields(values)
    if (Object.keys(nextFields).length) { showFields(nextFields); return }
    guard.current = true; setBusy(true); setError(''); setInfo(''); setFields({})
    try {
      // Confirmation is local-only; passwords are passed exactly as typed.
      const response = await api.changePassword({ current_password: values.current_password, new_password: values.new_password })
      if (!mounted.current) return
      clearPasswords()
      if (response.user.id !== user.id || response.user.role !== user.role) { onSignIn('Аккаунт изменился в другой вкладке. Войдите снова.'); return }
      onSessionUpdated(response); onSaved()
    } catch (reason) {
      if (!mounted.current) return
      const apiError = reason instanceof ApiError ? reason : null
      if (apiError?.status === 401) return // The shared client opens the sign-in screen.
      if (apiError?.code === 'ADMIN_ACCOUNT_PROTECTED') {
        clearPasswords(); setRecovery('csrf-unverified'); setError('Учётная запись администратора защищена от изменения через панель.')
        await checkSession(false)
      } else if (apiError?.code === 'CSRF_RECOVERED') {
        clearPasswords(); setRecovery('none'); setError(''); setInfo('Сессия обновлена. Заполните форму ещё раз.')
      } else if (apiError?.code === 'CSRF_REFRESH_FAILED') {
        clearPasswords(); setRecovery('csrf-unverified'); setError(apiError.message)
      } else if (apiError?.code === 'CSRF_FAILED') {
        clearPasswords(); setRecovery('csrf-unverified')
        setError('Сессия обновилась в другой вкладке. Запрос не применён.')
        await checkSession(false)
      } else if (apiError?.status === 0 || (apiError?.code === 'INVALID_RESPONSE' && apiError.status >= 200 && apiError.status < 300)) {
        clearPasswords(); setRecovery('uncertain-unverified')
        setError('Результат смены пароля не подтверждён. Изменение могло сохраниться.')
        await checkSession(true)
      } else {
        const next: PasswordErrors = {}
        for (const detail of apiError?.details || []) {
          if (definitions.some(item => item.key === detail.field)) next[detail.field as PasswordField] = detail.message
        }
        if (apiError?.code === 'CURRENT_PASSWORD_INVALID') next.current_password ||= 'Текущий пароль указан неверно.'
        if (apiError?.code === 'NEW_PASSWORD_UNCHANGED') next.new_password ||= 'Новый пароль должен отличаться от текущего.'
        showFields(next)
        if (apiError?.status === 429) {
          // Preserve the server deadline in App so closing the panel does not reset it.
          onRateLimit(Date.now() + (apiError.retryAfterSeconds ?? 60) * 1000)
          setNow(Date.now())
          setError('Слишком много попыток. Дождитесь окончания паузы.')
        } else if (apiError?.code === 'ORIGIN_NOT_ALLOWED') setError('Сервер не разрешил запрос с этого адреса сайта. Обратитесь к администратору.')
        else if (!Object.keys(next).length) setError(reason instanceof Error ? reason.message : 'Не удалось изменить пароль. Попробуйте позже.')
      }
    } finally { guard.current = false; if (mounted.current) setBusy(false) }
  }
  const blocked = recovery !== 'none'
  const uncertain = recovery.startsWith('uncertain')
  if (user.role !== 'user') return null
  return <Drawer title="Сменить пароль" subtitle="Безопасность вашей учётной записи." canClose={!busy && !checking} onClose={() => { if (!guard.current && !checking) onClose() }}>
    <div className="password-account"><span className="password-account-icon" aria-hidden="true"><KeyRound size={22}/></span><div><strong>{user.username}</strong><span>Пользователь</span></div></div>
    <div className="notice password-session-note"><ShieldCheck size={20} aria-hidden="true"/><p>Этот браузер останется в системе. На остальных устройствах потребуется войти снова.</p></div>
    <form className="change-password-form" onSubmit={submit} noValidate>
      <input type="text" name="username" autoComplete="username" value={user.username} readOnly hidden/>
      {definitions.map(field => {
        const id = `change-${field.key}`
        return <div className="field" key={field.key}><label htmlFor={id}>{field.label}</label><div className="password-field"><input ref={element => { inputs.current[field.key] = element || undefined }} id={id} name={field.key} type={shown[field.key] ? 'text' : 'password'} autoComplete={field.autoComplete} value={values[field.key]} required disabled={busy || checking || blocked} aria-invalid={Boolean(fields[field.key])} aria-describedby={[field.hint ? `${id}-hint` : '', fields[field.key] ? `${id}-error` : ''].filter(Boolean).join(' ') || undefined} onChange={event => { setValues(previous => ({ ...previous, [field.key]: event.target.value })); setFields(previous => ({ ...previous, [field.key]: undefined })) }}/><button className="password-toggle" type="button" disabled={busy || checking || blocked} aria-label={`${shown[field.key] ? 'Скрыть' : 'Показать'}: ${field.label.toLowerCase()}`} aria-pressed={Boolean(shown[field.key])} onClick={() => setShown(previous => ({ ...previous, [field.key]: !previous[field.key] }))}>{shown[field.key] ? <EyeOff size={18}/> : <Eye size={18}/>}</button></div>{field.hint && <small id={`${id}-hint`}>{field.hint}</small>}{fields[field.key] && <span className="field-error" id={`${id}-error`} role="alert">{fields[field.key]}</span>}</div>
      })}
      {error && <div className="password-feedback" role="alert"><AlertCircle size={19} aria-hidden="true"/><p>{error}</p></div>}
      {info && <p className="password-session-info" role="status">{info}</p>}
      {seconds > 0 && <p className="password-cooldown">Повторить можно через <span role="timer" aria-live="off">{seconds} сек.</span></p>}
      {uncertain && <p className="password-recovery-hint">Войдите заново с новым паролем. Если он не подходит, используйте прежний.</p>}
      {blocked ? <div className="password-recovery-actions">{recovery !== 'uncertain-restored' && <button className="btn btn-secondary" type="button" disabled={busy || checking} onClick={() => { if (guard.current) return; guard.current = true; void checkSession(uncertain).finally(() => { guard.current = false }) }}>{checking ? <span className="spinner"/> : <ShieldCheck size={17}/>} Проверить сессию</button>}<button className="btn btn-primary" type="button" disabled={busy || checking} onClick={() => onSignIn(uncertain ? 'Войдите с новым паролем. Если он не подходит, используйте прежний.' : 'Войдите снова, чтобы обновить сессию.')}>Войти снова</button></div> : <div className="form-actions password-form-actions"><button className="btn btn-primary" type="submit" disabled={busy || checking || seconds > 0}>{busy ? <span className="spinner"/> : <Check size={17}/>} {checking ? 'Проверяем сессию…' : busy ? 'Сохраняем…' : 'Сохранить пароль'}</button><button className="btn btn-secondary" type="button" disabled={busy || checking} data-drawer-close>Отмена</button></div>}
    </form>
  </Drawer>
}
