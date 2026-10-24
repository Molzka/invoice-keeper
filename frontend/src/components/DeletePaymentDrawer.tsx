import { useRef, useState } from 'react'
import { api, ApiError } from '../api/client'
import type { PaymentOccurrence, RecurringPayment } from '../types/api'
import { dateLabel, money } from '../lib/format'
import { Drawer, ErrorNotice } from './UI'

export function DeletePaymentDrawer({ target, onClose, onDeleted }: { target: { kind: 'period'; item: PaymentOccurrence } | { kind: 'recurring'; item: RecurringPayment }; onClose: () => void; onDeleted: () => void }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [uncertain, setUncertain] = useState(false)
  const guard = useRef(false)
  async function remove() {
    if (guard.current || uncertain) return
    guard.current = true; setBusy(true); setError(null)
    try {
      if (target.kind === 'period') await api.deleteOccurrence(target.item.id)
      else await api.archiveRecurringPayment(target.item.id)
      onDeleted()
    } catch (reason) {
      setError(reason)
      setUncertain(reason instanceof ApiError && (reason.status === 0 || reason.status >= 500 || reason.code === 'INVALID_RESPONSE'))
    } finally { guard.current = false; setBusy(false) }
  }
  return <Drawer title={target.kind === 'period' ? 'Удалить платёж?' : 'Удалить регулярный платёж?'} subtitle={target.item.title} canClose={!busy} onClose={onClose}>
    <div className="notice"><strong>История останется доступной.</strong><p>{target.kind === 'period' ? `Период со сроком ${dateLabel(target.item.due_date)} на ${money(target.item.amount, target.item.currency)} будет исключён из обязательств, сводки и напоминаний.${target.item.periodicity === 'once' ? '' : ' Следующие повторения сохранятся.'}` : 'Повторение прекратится. Все неоплаченные периоды будут исключены из обязательств и итогов. Оплаченные периоды и подтверждения останутся в истории.'}</p></div>
    <p className="muted">Удалённые периоды доступны в истории по переключателю «Показать удалённые» и защищены от изменения.</p>
    {error != null && <ErrorNotice error={error}/>}
    {uncertain && <p className="notice" role="status">Результат пока неизвестен. Закройте панель и проверьте обновлённый список перед повторной попыткой.</p>}
    <div className="form-actions"><button data-drawer-close type="button" className="btn btn-secondary" disabled={busy} onClick={onClose}>{uncertain ? 'Закрыть и проверить' : 'Отмена'}</button><button type="button" className="btn btn-danger" disabled={busy || uncertain} onClick={() => void remove()}>{busy ? 'Удаляем…' : 'Удалить'}</button></div>
  </Drawer>
}
