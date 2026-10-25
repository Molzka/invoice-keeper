import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import QRCode from 'qrcode'
import { Copy, Download, ShieldCheck } from './BrandIcons'
import { api, API_MODE, ApiError } from '../api/client'
import type { MfaFactor, MfaMethod, SecurityMutation, SecurityState, TelegramPaymentStatus, TelegramSetup, TelegramSetupStatus, TotpSetup, User } from '../types/api'
import { Drawer, ErrorNotice } from './UI'
import { TelegramPaymentLink } from './TelegramPaymentLink'

type Action = 'totp' | 'telegram' | 'recovery' | 'disable' | 'remove-totp' | 'remove-telegram' | 'payments-connect' | 'payments-disconnect'
const names: Record<MfaMethod, string> = { totp: 'Приложение-аутентификатор', telegram: 'Telegram', recovery: 'Резервный код' }
const actionNames: Record<Action, string> = { totp: 'Подключить приложение', telegram: 'Подключить Telegram', recovery: 'Обновить резервные коды', disable: 'Отключить дополнительную защиту', 'remove-totp': 'Отключить приложение', 'remove-telegram': 'Отключить Telegram', 'payments-connect': 'Подключить оплату в Telegram', 'payments-disconnect': 'Отключить оплату в Telegram' }

export function SecurityDrawer({ user, onClose, onPassword, onChanged }: { user: User; onClose: () => void; onPassword: () => void; onChanged: () => void }) {
  const [security, setSecurity] = useState<SecurityState | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const [action, setAction] = useState<Action | null>(null)
  const [password, setPassword] = useState('')
  const [method, setMethod] = useState<MfaMethod>('totp')
  const [code, setCode] = useState('')
  const [totp, setTotp] = useState<TotpSetup | null>(null)
  const [telegram, setTelegram] = useState<TelegramSetup | null>(null)
  const [telegramStatus, setTelegramStatus] = useState<TelegramSetupStatus | null>(null)
  const [paymentStatus, setPaymentStatus] = useState<TelegramPaymentStatus | null>(null)
  const [paymentSetup, setPaymentSetup] = useState<TelegramSetup | null>(null)
  const [paymentClaim, setPaymentClaim] = useState<TelegramSetupStatus | null>(null)
  const [qr, setQr] = useState('')
  const [codes, setCodes] = useState<string[] | null>(null)
  const [saved, setSaved] = useState(false)
  const [notice, setNotice] = useState('')
  const [retryAt, setRetryAt] = useState(0)
  const [submitRetryAt, setSubmitRetryAt] = useState(0)
  const [checkRequired, setCheckRequired] = useState(false)
  const [now, setNow] = useState(Date.now)
  const guard = useRef(false)
  const mounted = useRef(true)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  useEffect(() => {
    if (API_MODE !== 'real' || user.role !== 'user') return
    let active = true
    void Promise.all([api.security(), api.paymentTelegramStatus()]).then(([value, payment]) => { if (active) { setSecurity(value); setPaymentStatus(payment) } }).catch(reason => { if (active) setError(reason) })
    return () => { active = false }
  }, [user.id, user.role])
  useEffect(() => { const timer = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(timer) }, [])
  useEffect(() => {
    if (!totp) return
    let active = true
    void QRCode.toDataURL(totp.otpauth_uri, { width: 224, margin: 2, errorCorrectionLevel: 'M' }).then(value => { if (active) setQr(value) }).catch(() => { if (active) setNotice('Не удалось построить QR-код. Введите ключ в приложении вручную.') })
    return () => { active = false }
  }, [totp])
  async function run(task: () => Promise<void>) {
    if (guard.current) return
    guard.current = true; setBusy(true); setError(null)
    try { await task() } catch (reason) { if (mounted.current) { setError(reason); if (reason instanceof ApiError) { if (reason.retryAfterSeconds) { if (reason.code === 'MFA_RESEND_TOO_SOON') setRetryAt(Date.now() + reason.retryAfterSeconds * 1000); else setSubmitRetryAt(Date.now() + reason.retryAfterSeconds * 1000) } if (reason.status === 0 || reason.status >= 500 || ['TIMEOUT', 'NETWORK_ERROR', 'CSRF_REFRESH_FAILED', 'INVALID_RESPONSE'].includes(reason.code)) setCheckRequired(true) } } }
    finally { guard.current = false; if (mounted.current) setBusy(false) }
  }
  function reset() { setAction(null); setPassword(''); setCode(''); setTotp(null); setQr(''); setTelegram(null); setTelegramStatus(null); setPaymentSetup(null); setPaymentClaim(null); setError(null); setNotice('') }
  function begin(next: Action) { reset(); setAction(next); setMethod(security?.methods[0] || 'totp') }
  function applied(result: SecurityMutation) {
    if (!mounted.current) return
    reset(); setSecurity(result.security); setCodes(result.recovery_codes || null); setSaved(false); setNotice('Настройки сохранены. Остальные сессии завершены.'); onChanged()
  }
  async function authorize(event: FormEvent) {
    event.preventDefault()
    if (!action || !security || checkRequired || now < submitRetryAt) return
    await run(async () => {
      await api.reauth({ password, ...(security.mfa_enabled ? { method, code: code.trim() } : {}) })
      setPassword(''); setCode('')
      if (action === 'totp') setTotp(await api.setupTotp())
      else if (action === 'telegram') setTelegram(await api.setupTelegram())
      else if (action === 'recovery') applied(await api.regenerateRecovery())
      else if (action === 'disable') applied(await api.disableMfa())
      else if (action === 'payments-connect') { const value = await api.setupPaymentTelegram(); reset(); setPaymentSetup(value) }
      else if (action === 'payments-disconnect') { await api.unlinkPaymentTelegram(); const value = await api.paymentTelegramStatus(); reset(); setPaymentStatus(value); setNotice('Оплата в Telegram отключена. MFA не изменена.'); onChanged() }
      else applied(await api.removeFactor(action === 'remove-totp' ? 'totp' : 'telegram'))
    })
  }
  function downloadCodes() {
    if (!codes) return
    const url = URL.createObjectURL(new Blob(['Invoice Keeper — резервные коды\nКаждый код действует один раз. Храните отдельно от пароля.\n\n' + codes.join('\n')], { type: 'text/plain;charset=utf-8' }))
    const link = document.createElement('a'); link.href = url; link.download = 'invoice-keeper-recovery-codes.txt'; link.click(); URL.revokeObjectURL(url)
  }
  const setup = totp || telegram
  const expired = setup ? now >= Date.parse(setup.expires_at) : false
  const methods: MfaMethod[] = security ? [...security.methods, ...(security.recovery_codes_remaining ? ['recovery' as const] : [])] : []
  return <Drawer title="Безопасность" subtitle={user.username} onClose={onClose} canClose={!busy && (!codes || saved)}><div className="security-content">
    {API_MODE === 'mock' ? <><p className="access-note">Дополнительная защита доступна при подключении к серверу. В демонстрации можно изменить пароль.</p><button className="btn btn-secondary" onClick={onPassword}>Сменить пароль</button></> : <>
    {error ? <ErrorNotice error={error}/> : null}{checkRequired && <p className="access-note" role="alert">Результат действия не подтверждён. Сначала обновите сведения о защите: изменение могло сохраниться. Если набор резервных кодов не получен, создайте новый после подтверждения личности.</p>}{notice && <p className="access-note" role="status">{notice}</p>}
    {!security && !error && <p role="status">Загружаем настройки…</p>}
    {(error || checkRequired) && <button className="text-button" disabled={busy} onClick={() => void run(async () => { const [value, payment] = await Promise.all([api.security(), api.paymentTelegramStatus()]); reset(); setSecurity(value); setPaymentStatus(payment); setCheckRequired(false) })}>Обновить сведения о защите</button>}
    {security && !security.can_manage && <p>Защищённая учётная запись администратора не изменяется через панель.</p>}
    <div hidden={paymentSetup !== null}>
    {security?.can_manage && codes ? <section aria-labelledby="recovery-title"><h3 id="recovery-title">Сохраните резервные коды</h3><p>Они помогут войти, если телефон недоступен. Каждый код действует один раз. Этот набор показывается только сейчас; предыдущие коды больше не действуют.</p><ul className="recovery-codes">{codes.map(item => <li key={item}><code>{item}</code></li>)}</ul><div className="security-actions"><button className="btn btn-secondary" type="button" onClick={() => void navigator.clipboard.writeText(codes.join('\n')).then(() => setNotice('Коды скопированы. Сохраните их в надёжном месте.')).catch(() => setNotice('Не удалось скопировать. Скачайте коды или выделите текст.'))}><Copy size={16}/>Скопировать</button><button className="btn btn-secondary" type="button" onClick={downloadCodes}><Download size={16}/>Скачать</button></div><label className="security-check"><input type="checkbox" checked={saved} onChange={e => setSaved(e.target.checked)}/>Я сохранил резервные коды</label><button className="btn btn-primary" disabled={!saved} onClick={() => { setCodes(null); reset(); setNotice('Резервные коды сохранены.') }}>Готово</button></section> : security?.can_manage && setup ? <section><h3>{totp ? 'Подключите приложение' : 'Подключите личный Telegram'}</h3>{expired ? <p role="alert">Время настройки истекло. Начните подключение заново.</p> : <>
      {totp && <><p>Добавьте аккаунт в приложение-аутентификатор по QR-коду. Затем введите код из приложения.</p>{qr && <img className="security-qr" src={qr} width="224" height="224" alt="QR-код для подключения приложения-аутентификатора"/>}<details><summary>Ввести ключ вручную</summary><code className="security-secret">{totp.secret}</code></details></>}
      {telegram && <><p>Откройте ссылку и нажмите «Запустить» в личном чате с ботом. После этого вернитесь сюда.</p><a className="btn btn-primary" href={telegram.link} target="_blank" rel="noreferrer">Открыть Telegram</a><button className="btn btn-secondary access-send" disabled={busy} onClick={() => void run(async () => setTelegramStatus(await api.telegramSetupStatus(telegram.setup_id)))}>Проверить привязку</button>{telegramStatus?.status === 'claimed' && telegramStatus.account ? <p className="access-note">Найден аккаунт: <strong>{telegramStatus.account.display_name}</strong>{telegramStatus.account.username ? ` (@${telegramStatus.account.username})` : ''}. Если это ваш аккаунт, введите присланный код.</p> : <p role="status">Ожидаем запуск бота по одноразовой ссылке.</p>}</>}
      <form onSubmit={e => { e.preventDefault(); if (checkRequired || now < submitRetryAt) return; void run(async () => applied(totp ? await api.confirmTotp(totp.setup_id, code.trim()) : await api.confirmTelegram(telegram!.setup_id, code.trim()))) }}><div className="field"><label htmlFor="setup-code">Код подтверждения</label><input id="setup-code" value={code} onChange={e => setCode(e.target.value)} inputMode="numeric" autoComplete="one-time-code" required disabled={busy}/></div><button className="btn btn-primary" disabled={busy || checkRequired || now < submitRetryAt || (Boolean(telegram) && telegramStatus?.status !== 'claimed')}>Подключить защиту</button></form>
    </>}<button className="text-button access-back" disabled={busy} onClick={reset}>Отменить настройку</button></section> : security?.can_manage && action ? <section><h3>{actionNames[action]}</h3><p>{action === 'disable' ? 'После отключения для входа понадобится только пароль. Все резервные коды будут отозваны.' : action.startsWith('remove-') && security.methods.length === 1 ? 'Это последний способ подтверждения. После его удаления дополнительная защита отключится, резервные коды будут отозваны.' : action === 'recovery' ? 'Старый набор кодов перестанет действовать. Новый набор будет показан один раз.' : 'Сначала подтвердите, что это вы. Разрешение на изменение действует пять минут.'}</p><form onSubmit={e => void authorize(e)}><div className="field"><label htmlFor="security-password">Текущий пароль</label><input id="security-password" type="password" autoComplete="current-password" value={password} onChange={e => setPassword(e.target.value)} required disabled={busy}/></div>{security.mfa_enabled && <><div className="field"><label htmlFor="security-method">Подтвердить с помощью</label><select id="security-method" value={method} disabled={busy} onChange={e => { setMethod(e.target.value as MfaMethod); setCode('') }}>{methods.map(item => <option key={item} value={item}>{names[item]}</option>)}</select></div>{method === 'telegram' && <button className="btn btn-secondary access-send" type="button" disabled={busy || !password || now < retryAt} onClick={() => void run(async () => { const sent = await api.sendSecurityTelegram(password); setRetryAt(Date.now() + sent.retry_after * 1000); setNotice('Код отправлен в личный чат.') })}>{now < retryAt ? `Повторить через ${Math.ceil((retryAt - now) / 1000)} с` : 'Отправить код в Telegram'}</button>}<div className="field"><label htmlFor="security-code">{method === 'recovery' ? 'Резервный код' : 'Код подтверждения'}</label><input id="security-code" value={code} onChange={e => setCode(e.target.value)} autoComplete="one-time-code" inputMode={method === 'recovery' ? 'text' : 'numeric'} required disabled={busy}/></div></>}<button className={`btn ${action === 'disable' || action.startsWith('remove-') ? 'btn-danger' : 'btn-primary'}`} disabled={busy || checkRequired || now < submitRetryAt}>{busy ? 'Проверяем…' : actionNames[action]}</button></form><button className="text-button access-back" disabled={busy} onClick={reset}>Отмена</button></section> : security?.can_manage && <><div className="security-status"><ShieldCheck size={24}/><div><h3>{security.mfa_enabled ? 'Вход защищён' : 'Дополнительная защита не подключена'}</h3><p>{security.mfa_enabled ? 'При каждом новом входе нужен пароль и код.' : 'Подключение добровольное. Все функции доступны и без него.'}</p></div></div><div className="security-row"><div><h3>Пароль</h3><p>Изменить пароль этой учётной записи.</p></div><button className="btn btn-secondary btn-small" onClick={onPassword}>Сменить пароль</button></div>{(['totp', 'telegram'] as MfaFactor[]).map(item => { const enabled = security.methods.includes(item); const available = security.available_methods.includes(item); return <div className="security-row" key={item}><div><h3>{names[item]}</h3><p>{enabled ? item === 'telegram' && security.telegram ? `Подключён: ${security.telegram.display_name}${security.telegram.username ? ` (@${security.telegram.username})` : ''}` : 'Подключено' : available ? item === 'totp' ? 'Коды в приложении на вашем телефоне.' : 'Коды в личном чате с ботом.' : 'Сейчас недоступно. Обратитесь к администратору.'}</p></div><div className="security-actions">{available && <button className="btn btn-secondary btn-small" onClick={() => begin(item)}>{enabled ? 'Заменить' : 'Подключить'}</button>}{enabled && <button className="btn btn-danger btn-small" onClick={() => begin(`remove-${item}`)}>Отключить</button>}</div></div> })}{security.mfa_enabled && <><div className="security-row"><div><h3>Резервные коды</h3><p>Осталось: {security.recovery_codes_remaining}. Для входа при потере телефона.</p></div><button className="btn btn-secondary btn-small" onClick={() => begin('recovery')}>Получить новые</button></div><button className="text-button security-disable" onClick={() => begin('disable')}>Отключить дополнительную защиту</button></>}{security.mfa_enabled && <p className="access-note">Если потеряны все способы подтверждения и резервные коды, обратитесь к администратору. Автоматического обхода защиты нет.</p>}</>}
    </div>
    {security?.can_manage && paymentStatus && !action && !setup && !codes && <TelegramPaymentLink
      status={paymentStatus} setup={paymentSetup} claim={paymentClaim} now={now}
      disabled={busy || checkRequired || now < submitRetryAt}
      onConnect={() => begin('payments-connect')} onDisconnect={() => begin('payments-disconnect')} onCancel={reset}
      onCheck={() => { if (paymentSetup) void run(async () => setPaymentClaim(await api.paymentTelegramSetupStatus(paymentSetup.setup_id))) }}
      onConfirm={() => { const account = paymentClaim?.account; if (paymentSetup && account) void run(async () => { const value = await api.confirmPaymentTelegram(paymentSetup.setup_id, account.id); reset(); setPaymentStatus(value); setNotice('Telegram для оплаты подключён. MFA не изменена.'); onChanged() }) }}
    />}
    </>}
  </div></Drawer>
}
