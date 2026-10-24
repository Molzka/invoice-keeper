import { useCallback, useEffect, useId, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { AlertCircle, ChevronLeft, ChevronRight, Inbox, X } from './BrandIcons'
import { ApiError, isMissingPaymentRoute } from '../api/client'


export function Drawer({ title, subtitle, children, onClose, canClose = true }: { title: string; subtitle?: string; children: ReactNode; onClose: () => void; canClose?: boolean }) {
  const titleId = useId()
  const panel = useRef<HTMLDivElement>(null)
  const closeRef = useRef(onClose)
  const canCloseRef = useRef(canClose)
  const closingRef = useRef(false)
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const [closing, setClosing] = useState(false)
  closeRef.current = onClose
  canCloseRef.current = canClose
  const requestClose = useCallback(() => {
    if (!canCloseRef.current || closingRef.current) return
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      closeRef.current()
      return
    }
    closingRef.current = true
    setClosing(true)
    closeTimer.current = setTimeout(() => {
      closeTimer.current = null
      closingRef.current = false
      setClosing(false)
      // The parent keeps the final say if a request began during the exit.
      if (canCloseRef.current) closeRef.current()
    }, 180)
  }, [])
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const focusable = () => Array.from(panel.current?.querySelectorAll<HTMLElement>('a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]):not(.ik-select-native), textarea:not([disabled]), [tabindex="0"]') || []).filter(el => el.tabIndex >= 0 && !el.closest('[hidden], [inert], [aria-hidden="true"]') && el.getClientRects().length > 0 && getComputedStyle(el).visibility !== 'hidden')
    focusable()[0]?.focus()
    const onKey = (event: KeyboardEvent) => {
      if (event.defaultPrevented) return
      if (closingRef.current && ['Tab', 'Enter', 'Escape', ' '].includes(event.key)) { event.preventDefault(); return }
      if (event.key === 'Escape') { event.preventDefault(); requestClose(); return }
      if (event.key !== 'Tab') return
      const items = focusable()
      const first = items[0], last = items[items.length - 1]
      if (!first) return
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
    }
    document.addEventListener('keydown', onKey)
    return () => { if (closeTimer.current) clearTimeout(closeTimer.current); document.body.style.overflow = previousOverflow; document.removeEventListener('keydown', onKey); if (previous?.isConnected) previous.focus(); else document.querySelector<HTMLElement>('.page-title')?.focus() }
  }, [requestClose])
  return createPortal(<div className="drawer-backdrop" role="dialog" aria-modal="true" aria-labelledby={titleId} data-state={closing ? 'closing' : 'open'} onMouseDown={event => { if (event.target === event.currentTarget) requestClose() }}>
    <div ref={panel} className="drawer" onClickCapture={event => {
      if (event.defaultPrevented || !(event.target instanceof Element)) return
      const action = event.target.closest('[data-drawer-close]')
      if (!action || !event.currentTarget.contains(action)) return
      event.preventDefault()
      event.stopPropagation()
      requestClose()
    }}>
      <div className="drawer-head"><div><h2 id={titleId}>{title}</h2>{subtitle && <p>{subtitle}</p>}</div><button className="icon-button" type="button" aria-label="Закрыть панель" disabled={!canClose || closing} onClick={requestClose}><X size={18}/></button></div>
      <div className="drawer-body">{children}</div>
    </div>
    <div className="drawer-popover-root" data-drawer-popover-root=""/>
  </div>, document.body)
}
export function ErrorNotice({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const apiError = error instanceof ApiError ? error : null
  const forbidden = apiError?.status === 403
  const waiting = apiError?.code === 'PERIODS_NOT_READY'
  const missingPaymentApi = isMissingPaymentRoute(error)
  const title = waiting ? 'Сводка ещё не готова' : forbidden ? 'Недостаточно прав' : missingPaymentApi ? 'Платёжный API недоступен' : 'Не удалось выполнить запрос'
  const message = waiting
    ? 'Сервер восстанавливает периоды платежей. Итоги появятся после завершения — сейчас они не равны нулю.'
    : missingPaymentApi
      ? 'Сервер не нашёл маршрут этого раздела. Проверьте подключение платёжного модуля и адрес API. Данные и итоги сейчас недоступны.'
      : error instanceof Error ? error.message : 'Попробуйте повторить запрос.'
  return <div className={waiting ? 'summary-error' : 'error-banner'} role="alert">
    <AlertCircle size={20} aria-hidden="true"/>
    <div>
      <h3>{title}</h3><p>{message}</p>
      {missingPaymentApi && apiError?.request && <details className="api-request-detail"><summary>Технические детали</summary><code>{apiError.request.method} {apiError.request.path} · HTTP {apiError.status}</code></details>}
      {apiError?.details.length ? <ul>{apiError.details.map((item, index) => <li key={index}>{item.message}</li>)}</ul> : null}
      {onRetry && <button type="button" className="btn btn-secondary btn-small" onClick={onRetry}>Повторить загрузку</button>}
    </div>
  </div>
}
export function Pagination({ total, limit, offset, onPage }: { total: number; limit: number; offset: number; onPage: (offset: number) => void }) {
  const start = total ? offset + 1 : 0
  return <div className="pagination"><span>{start}–{Math.min(offset + limit, total)} из {total}</span><div className="inline-actions"><button type="button" className="icon-button" aria-label="Предыдущая страница" disabled={offset === 0} onClick={() => onPage(Math.max(0, offset - limit))}><ChevronLeft size={18}/></button><button type="button" className="icon-button" aria-label="Следующая страница" disabled={offset + limit >= total} onClick={() => onPage(offset + limit)}><ChevronRight size={18}/></button></div></div>
}
export function EmptyState({ title, children }: { title: string; children?: ReactNode }) { return <div className="empty-state"><Inbox size={28} aria-hidden="true"/><h3>{title}</h3>{children && <p>{children}</p>}</div> }
export function LoadingRows() { return <div className="loading-list" role="status" aria-label="Загрузка платежей">{[1,2,3,4].map(item => <div key={item} className="skeleton" style={{ height: 56, margin: '12px 24px' }}/>)}</div> }
