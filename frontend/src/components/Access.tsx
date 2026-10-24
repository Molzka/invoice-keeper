import { useEffect, useRef, useState, useSyncExternalStore } from 'react'
import type { FormEvent } from 'react'
import { ShieldCheck } from './BrandIcons'
import { api, API_MODE, ApiError, BASE_URL } from '../api/client'
import type { AuthResponse, MfaChallenge, MfaMethod } from '../types/api'
import { BrandLogin } from './BrandLogin'

const methodNames: Record<MfaMethod, string> = { totp: 'Приложение-аутентификатор', telegram: 'Telegram', recovery: 'Резервный код' }
function subscribeRoute(callback: () => void) { window.addEventListener('hashchange', callback); return () => window.removeEventListener('hashchange', callback) }
function accessRoute() { return window.location.hash === '#request-access' }

function Captcha({ onVerified }: { onVerified: (payload: string) => void }) {
  const host = useRef<HTMLDivElement>(null)
  const [failed, setFailed] = useState(false)
  const [revision, setRevision] = useState(0)
  useEffect(() => {
    let active = true
    let widget: HTMLElement | undefined
    void Promise.all([import('altcha'), import('altcha/i18n/ru')]).then(() => {
      if (!active || !host.current) return
      widget = document.createElement('altcha-widget')
      widget.setAttribute('challenge', BASE_URL + '/registration/challenge')
      widget.setAttribute('language', 'ru')
      widget.addEventListener('statechange', event => {
        const detail = (event as CustomEvent<{ state: string; payload?: string }>).detail
        onVerified(detail.state === 'verified' ? detail.payload || '' : '')
      })
      host.current.replaceChildren(widget)
    }).catch(() => { if (active) setFailed(true) })
    return () => { active = false; widget?.remove() }
  }, [onVerified, revision])
  return <div className="access-captcha"><div ref={host}/>{failed && <p role="alert">Не удалось загрузить проверку. <button type="button" className="text-button" onClick={() => { setFailed(false); setRevision(value => value + 1) }}>Повторить</button></p>}</div>
}

function Registration({ onBack }: { onBack: () => void }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [message, setMessage] = useState('')
  const [altcha, setAltcha] = useState('')
  const [captchaKey, setCaptchaKey] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [accepted, setAccepted] = useState('')
  const guard = useRef(false)
  async function submit(event: FormEvent) {
    event.preventDefault()
    if (guard.current) return
    if (Array.from(password).length < 8 || Array.from(password).length > 128) { setError('Пароль должен содержать от 8 до 128 символов.'); return }
    if (password !== confirm) { setError('Пароли не совпадают.'); return }
    if (!message.trim() || Array.from(message).length > 500) { setError('Укажите имя или сообщение до 500 символов.'); return }
    if (!altcha) { setError('Пройдите проверку перед отправкой.'); return }
    guard.current = true; setBusy(true); setError('')
    try { const result = await api.register({ username, password, password_confirm: confirm, message, altcha }); setPassword(''); setConfirm(''); setAccepted(result.message) }
    catch (reason) { setError(reason instanceof ApiError && reason.details.length ? reason.details.map(item => item.message).join(' ') : reason instanceof Error ? reason.message : 'Не удалось отправить заявку.'); setAltcha(''); setCaptchaKey(value => value + 1) }
    finally { guard.current = false; setBusy(false) }
  }
  if (accepted) return <div className="access-result" role="status"><ShieldCheck size={28}/><h1 className="login-heading">Заявка отправлена</h1><p>{accepted}</p><p>Одобрение не приходит автоматически: уточните решение у администратора команды.</p><button type="button" className="btn btn-primary" onClick={onBack}>Вернуться ко входу</button></div>
  return <><h1 className="login-heading">Запросить доступ</h1><p className="login-caption">Сервис для сотрудников. Администратор проверит заявку; до одобрения данные команды недоступны.</p>{error && <div className="error-banner" role="alert">{error}</div>}<form onSubmit={submit}>
    <div className="field"><label htmlFor="request-username">Логин</label><input id="request-username" autoComplete="username" value={username} onChange={e => setUsername(e.target.value)} required disabled={busy} minLength={3} maxLength={64}/><small>От 3 до 64 символов: латинские буквы, цифры, точка, дефис или подчёркивание.</small></div>
    <div className="field"><label htmlFor="request-password">Пароль</label><input id="request-password" type="password" autoComplete="new-password" value={password} onChange={e => setPassword(e.target.value)} required disabled={busy}/><small>От 8 до 128 символов.</small></div>
    <div className="field"><label htmlFor="request-confirm">Повторите пароль</label><input id="request-confirm" type="password" autoComplete="new-password" value={confirm} onChange={e => setConfirm(e.target.value)} required disabled={busy}/></div>
    <div className="field"><label htmlFor="request-message">Имя или сообщение администратору</label><textarea id="request-message" value={message} onChange={e => setMessage(e.target.value)} required disabled={busy} rows={3}/></div>
    {API_MODE === 'real' ? <Captcha key={captchaKey} onVerified={setAltcha}/> : <p className="access-note">Заявки доступны при подключении к серверу. Демонстрация не создаёт аккаунты.</p>}
    <button className="btn btn-primary" disabled={busy || !altcha} type="submit">{busy ? 'Отправляем…' : 'Отправить заявку'}</button>
  </form><button className="text-button access-back" type="button" disabled={busy} onClick={onBack}>Уже есть доступ? Войти</button></>
}

function Challenge({ challenge, onLogin, onCancel }: { challenge: MfaChallenge; onLogin: (session: AuthResponse) => void; onCancel: () => void }) {
  const [method, setMethod] = useState<MfaMethod>(challenge.methods[0])
  const [code, setCode] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [retryAt, setRetryAt] = useState(0)
  const [verifyRetryAt, setVerifyRetryAt] = useState(0)
  const [invalidated, setInvalidated] = useState(false)
  const [now, setNow] = useState(Date.now)
  const guard = useRef(false)
  const expired = invalidated || now >= Date.parse(challenge.expires_at)
  useEffect(() => { const timer = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(timer) }, [])
  async function run(action: () => Promise<void>) {
    if (guard.current) return
    guard.current = true; setBusy(true); setError('')
    try { await action() } catch (reason) { setError(reason instanceof Error ? reason.message : 'Не удалось проверить код.'); if (reason instanceof ApiError) { if (reason.code === 'MFA_CHALLENGE_EXPIRED') setInvalidated(true); if (reason.retryAfterSeconds) { if (reason.code === 'MFA_RESEND_TOO_SOON') setRetryAt(Date.now() + reason.retryAfterSeconds * 1000); else setVerifyRetryAt(Date.now() + reason.retryAfterSeconds * 1000) } } }
    finally { guard.current = false; setBusy(false) }
  }
  return <><h1 className="login-heading">Подтвердите вход</h1><p className="login-caption">Введите код подключённого способа защиты. Рабочее пространство откроется после проверки.</p>{error && <div className="error-banner" role="alert">{error}</div>}{expired ? <p role="alert">Время подтверждения истекло. Вернитесь ко входу и введите пароль заново.</p> : <form onSubmit={e => { e.preventDefault(); void run(async () => onLogin(await api.verifyMfa(method, code.trim())) ) }}><div className="field"><label htmlFor="login-method">Способ подтверждения</label><select id="login-method" value={method} disabled={busy} onChange={e => { setMethod(e.target.value as MfaMethod); setCode(''); setNotice(''); setError('') }}>{challenge.methods.map(item => <option key={item} value={item}>{methodNames[item]}</option>)}</select></div>{method === 'telegram' && <button className="btn btn-secondary access-send" type="button" disabled={busy || now < retryAt} onClick={() => void run(async () => { const sent = await api.sendLoginTelegram(); setRetryAt(Date.now() + sent.retry_after * 1000); setNotice('Код отправлен в личный чат с ботом.') })}>{now < retryAt ? `Отправить снова через ${Math.ceil((retryAt - now) / 1000)} с` : 'Отправить код в Telegram'}</button>}{notice && <p role="status">{notice}</p>}<div className="field"><label htmlFor="login-code">{method === 'recovery' ? 'Резервный код' : 'Код подтверждения'}</label><input id="login-code" value={code} onChange={e => setCode(e.target.value)} autoComplete="one-time-code" inputMode={method === 'recovery' ? 'text' : 'numeric'} required disabled={busy}/><small>{method === 'recovery' ? 'Каждый резервный код можно использовать один раз.' : 'Код действует ограниченное время.'}</small></div><button className="btn btn-primary" type="submit" disabled={busy || now < verifyRetryAt}>{busy ? 'Проверяем…' : now < verifyRetryAt ? `Повторить через ${Math.ceil((verifyRetryAt - now) / 1000)} с` : 'Подтвердить вход'}</button></form>}<button className="text-button access-back" type="button" disabled={busy} onClick={() => void run(async () => { try { await api.cancelMfa() } catch { /* A pending login grants no access and expires on the server; local back must remain usable. */ } onCancel() })}>Вернуться ко входу</button></>
}

export function Access({ onLogin, restoreError, onRestore }: { onLogin: (session: AuthResponse) => void; restoreError: unknown; onRestore: () => void }) {
  const registration = useSyncExternalStore(subscribeRoute, accessRoute)
  const [challenge, setChallenge] = useState<MfaChallenge | null>(null)
  const back = () => { window.location.hash = 'payments' }
  const content = challenge
    ? <Challenge challenge={challenge} onLogin={onLogin} onCancel={() => setChallenge(null)}/>
    : registration ? <Registration onBack={back}/> : undefined
  return <BrandLogin onLogin={onLogin} onMfaChallenge={setChallenge} accessContent={content} restoreError={restoreError} onRestore={onRestore}/>
}
