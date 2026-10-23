import { useEffect, useId, useRef } from 'react'
import type { ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { AlertCircle, ChevronLeft, ChevronRight, Inbox, X } from 'lucide-react'
import { ApiError } from '../api/client'

export function Drawer({ title, subtitle, children, onClose }: { title: string; subtitle?: string; children: ReactNode; onClose: () => void }) {
  const titleId = useId()
  const panel = useRef<HTMLDivElement>(null)
  const closeRef = useRef(onClose)
  closeRef.current = onClose
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const target = panel.current?.querySelector<HTMLElement>('input:not([disabled]), select:not([disabled]), button:not([disabled])')
    target?.focus()
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); closeRef.current(); return }
      if (event.key !== 'Tab') return
      const items = Array.from(panel.current?.querySelectorAll<HTMLElement>('a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex="0"]') || []).filter(el => el.getClientRects().length > 0)
      const first = items[0], last = items[items.length - 1]
      if (!first) return
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
    }
    document.addEventListener('keydown', onKey)
    return () => { document.body.style.overflow = previousOverflow; document.removeEventListener('keydown', onKey); if (previous?.isConnected) previous.focus(); else document.querySelector<HTMLElement>('.page-title')?.focus() }
  }, [])
  return createPortal(<div className="drawer-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) onClose() }}>
    <div ref={panel} className="drawer" role="dialog" aria-modal="true" aria-labelledby={titleId}>
      <div className="drawer-head"><div><h2 id={titleId}>{title}</h2>{subtitle && <p>{subtitle}</p>}</div><button className="icon-button" type="button" aria-label="Закрыть панель" onClick={onClose}><X size={18}/></button></div>
      <div className="drawer-body">{children}</div>
    </div>
  </div>, document.body)
}
export function ErrorNotice({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const apiError = error instanceof ApiError ? error : null
  const forbidden = apiError?.status === 403
  const waiting = apiError?.code === 'PERIODS_NOT_READY'
  const title = waiting ? 'Сводка ещё не готова' : forbidden ? 'Недостаточно прав' : 'Не удалось выполнить запрос'
  const message = waiting ? 'Сервер восстанавливает периоды платежей. Итоги появятся после завершения — сейчас они не равны нулю.' : error instanceof Error ? error.message : 'Попробуйте повторить запрос.'
  return <div className={waiting ? 'summary-error' : 'error-banner'} role="alert"><AlertCircle size={20} aria-hidden="true"/><div><h3>{title}</h3><p>{message}</p>{apiError?.details.length ? <ul>{apiError.details.map((item, index) => <li key={index}>{item.message}</li>)}</ul> : null}{onRetry && <button type="button" className="btn btn-secondary btn-small" onClick={onRetry}>Повторить загрузку</button>}</div></div>
}
export function Pagination({ total, limit, offset, onPage }: { total: number; limit: number; offset: number; onPage: (offset: number) => void }) {
  const start = total ? offset + 1 : 0
  return <div className="pagination"><span>{start}–{Math.min(offset + limit, total)} из {total}</span><div className="inline-actions"><button type="button" className="icon-button" aria-label="Предыдущая страница" disabled={offset === 0} onClick={() => onPage(Math.max(0, offset - limit))}><ChevronLeft size={18}/></button><button type="button" className="icon-button" aria-label="Следующая страница" disabled={offset + limit >= total} onClick={() => onPage(offset + limit)}><ChevronRight size={18}/></button></div></div>
}
export function EmptyState({ title, children }: { title: string; children?: ReactNode }) { return <div className="empty-state"><Inbox size={28} aria-hidden="true"/><h3>{title}</h3>{children && <p>{children}</p>}</div> }
export function LoadingRows() { return <div className="loading-list" role="status" aria-label="Загрузка платежей">{[1,2,3,4].map(item => <div key={item} className="skeleton" style={{ height: 56, margin: '12px 24px' }}/>)}</div> }
