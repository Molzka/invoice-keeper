import type { Page } from './api'

export const AUDIT_ACTIONS = ['payment.created', 'payment.stopped', 'payment.paid', 'payment.unpaid', 'payment.date_changed', 'payment.receipt_updated', 'payment.receipt_deleted', 'user.created', 'user.updated', 'user.deleted', 'password.changed', 'registration.approved', 'registration.rejected', 'account.mfa_enabled', 'account.mfa_disabled', 'account.mfa_changed', 'account.recovery_regenerated'] as const
export type AuditAction = typeof AUDIT_ACTIONS[number]
export const AUDIT_ACTION_LABELS: Record<AuditAction, string> = {
  'payment.created': 'Создан платёж', 'payment.stopped': 'Платёж прекращён',
  'payment.paid': 'Отмечена оплата', 'payment.unpaid': 'Отменена оплата',
  'payment.date_changed': 'Исправлена дата оплаты', 'user.created': 'Создан пользователь',
  'user.updated': 'Изменён пользователь', 'user.deleted': 'Удалён пользователь',
  'password.changed': 'Изменён пароль',
  'registration.approved': 'Заявка одобрена',
  'registration.rejected': 'Заявка отклонена',
  'account.mfa_enabled': 'Защита входа подключена',
  'account.mfa_disabled': 'Защита входа отключена',
  'account.mfa_changed': 'Способы защиты изменены',
  'account.recovery_regenerated': 'Резервные коды обновлены',

  'payment.receipt_updated': 'Обновлено подтверждение оплаты',
  'payment.receipt_deleted': 'Удалено подтверждение оплаты',
}
export interface AuditChange { field: string; label: string; before: string | null; after: string | null }
export interface AuditEvent {
  id: string
  occurred_at: string
  actor: { id: string; username: string }
  action: AuditAction
  /** Payment entities always use the recurring payment ID, including period mutations. */
  entity: { type: 'payment' | 'user' | 'account' | 'registration'; id: string; title: string }
  changes: AuditChange[]
}
export interface AuditFilters {
  date_from: string
  date_to: string
  actor: string
  action: AuditAction | ''
  query: string
  limit: number
  offset: number
}
export type AuditPage = Page<AuditEvent>
