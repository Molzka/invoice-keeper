import { Check } from 'lucide-react'
import type { PaymentOccurrence } from '../types/api'
import { statusInfo } from '../lib/format'

export function PaymentStatus({ item }: { item: PaymentOccurrence }) {
  const info = statusInfo(item)
  if (item.status === 'paid' && item.paid_late) {
    return <span className="status status-warning status-late">
      <span className="status-check" aria-hidden="true"><Check size={11} strokeWidth={2.3} /></span>
      <span className="status-copy"><strong>Оплачено</strong>{' '}<span>с опозданием</span></span>
    </span>
  }
  return <span className={`status ${info.className}`}>{info.text}</span>
}
