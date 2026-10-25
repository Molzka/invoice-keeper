import type { TelegramPaymentStatus, TelegramSetup, TelegramSetupStatus } from '../types/api'

type Props = {
  status: TelegramPaymentStatus; setup: TelegramSetup | null; claim: TelegramSetupStatus | null
  now: number; disabled: boolean; onConnect: () => void; onDisconnect: () => void
  onCheck: () => void; onConfirm: () => void; onCancel: () => void
}

export function TelegramPaymentLink({ status, setup, claim, now, disabled, onConnect, onDisconnect, onCheck, onConfirm, onCancel }: Props) {
  const expired = setup !== null && now >= Date.parse(setup.expires_at)
  return <section className="telegram-payment-link" data-setup={setup !== null} aria-labelledby="telegram-payments-title">
    <h3 id="telegram-payments-title">Оплата в Telegram</h3>
    <p>Привяжите личный аккаунт, чтобы отмечать оплату кнопкой в рабочем чате. Настройки защиты входа при этом не меняются.</p>
    {!status.available && <p className="access-note">Подключение пока недоступно. Попросите администратора настроить бота.</p>}
    {setup ? <>
      {expired ? <p role="alert">Время привязки истекло. Закройте настройку и создайте новую ссылку.</p> : <>
        <ol><li>Откройте ссылку и нажмите «Запустить» в личном чате с ботом.</li><li>Вернитесь в эту вкладку и проверьте найденный аккаунт.</li><li>Подтвердите, что это ваш аккаунт.</li></ol>
        <div className="security-actions">
          <a className="btn btn-secondary" href={setup.link} target="_blank" rel="noreferrer">Открыть бота для привязки</a>
          <button className="btn btn-secondary" disabled={disabled} onClick={onCheck}>Проверить аккаунт</button>
        </div>
        {claim?.status === 'claimed' && claim.account ? <>
          <p className="access-note telegram-payment-account"><strong>{claim.account.display_name}</strong><br/>{claim.account.username ? `@${claim.account.username} · ` : ''}ID {claim.account.id}</p>
          <p>Подтверждайте только свой аккаунт. Если имя или ID не ваши, отмените настройку.</p>
          <button className="btn btn-primary" disabled={disabled} onClick={onConfirm}>Подтвердить мой Telegram</button>
        </> : <p role="status">Ожидаем открытие ссылки в Telegram.</p>}
      </>}
      <button className="text-button access-back" disabled={disabled} onClick={onCancel}>Отменить настройку оплаты</button>
    </> : <>
      {status.account ? <p className="access-note telegram-payment-account">Подключён: <strong>{status.account.display_name}</strong><br/>ID {status.account.id}</p> : <p className="muted">Аккаунт для оплаты ещё не подключён.</p>}
      <div className="security-actions">
        <button className="btn btn-secondary" disabled={disabled || !status.available} onClick={onConnect}>{status.account ? 'Изменить Telegram для оплаты' : 'Подключить оплату в Telegram'}</button>
        {status.account && <button className="btn btn-danger" disabled={disabled} onClick={onDisconnect}>Отключить оплату в Telegram</button>}
      </div>
    </>}
  </section>
}
