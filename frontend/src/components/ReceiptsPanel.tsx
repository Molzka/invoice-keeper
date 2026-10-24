import { useEffect, useId, useRef, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import type { Currency } from '../types/api'
import { ApiError } from '../api/errors'
import { dateLabel, money } from '../lib/format'
import { normalizeReceiptUrl, receiptFileSize, receiptHostname } from '../lib/receipt-links'
import { AlertCircle, ArrowUpRight, Check, FileText, Info, Link as LinkIcon, Paperclip, PencilLine, ReceiptText, RefreshCw, Search } from './BrandIcons'
import { PageHeader } from './PageHeader'
import { SelectField } from './SelectField'
import { EmptyState, ErrorNotice, Pagination } from './UI'

/** Internal display model. The API adapter owns endpoint and response mapping. */
export interface ReceiptAttachment {
  id: string
  kind: 'link' | 'file'
  url: string
  label: string
  file_name?: string
  size_bytes?: number
}
export interface ReceiptEntry {
  id: string
  occurrence_id: string
  title: string
  amount: string
  currency: Currency
  due_date: string
  paid_on: string | null
  attachments: ReceiptAttachment[]
  can_edit?: boolean
}
export interface ReceiptFilters {
  query: string
  currency: Currency | ''
  kind: 'all' | 'link' | 'file' | 'missing'
}
export interface ReceiptSummary {
  payments: number
  files: number
  links: number
  missing: number
}
export interface ReceiptsPanelProps {
  items: ReceiptEntry[]
  loading: boolean
  error?: unknown
  onRetry: () => void
  filters: ReceiptFilters
  onFiltersChange: (filters: ReceiptFilters) => void
  total: number | null
  limit: number
  offset: number
  onPage: (offset: number) => void
  /** Counts supplied by the server, never inferred from a paginated list. */
  summary?: ReceiptSummary | null
  summaryLoading?: boolean
  summaryError?: unknown
  onSummaryRetry?: () => void
  onEdit?: (entry: ReceiptEntry) => void
  onOpenPayment?: (occurrenceId: string) => void
  eyebrow?: ReactNode
}
function defaultReceiptFilters(): ReceiptFilters { return { query: '', currency: '', kind: 'all' } }

const currencyOptions = [
  { value: '', label: 'Все валюты' },
  { value: 'RUB', label: 'RUB', description: 'Рубли' },
  { value: 'USD', label: 'USD', description: 'Доллары' },
  { value: 'EUR', label: 'EUR', description: 'Евро' },
]
const kindOptions = [
  { value: 'all', label: 'Все материалы' },
  { value: 'file', label: 'Файлы чеков' },
  { value: 'link', label: 'Ссылки' },
  { value: 'missing', label: 'Без материалов' },
]
const countFormat = new Intl.NumberFormat('ru-RU')
function countLabel(count: number) { return Number.isSafeInteger(count) && count >= 0 ? countFormat.format(count) : '—' }

function ReceiptSummaryCards({ summary }: { summary: ReceiptSummary }) {
  return <dl className="receipts-summary" aria-label="Сводка материалов по данным сервера">
    {[
      { label: 'Платежей', count: summary.payments, icon: ReceiptText, tone: 'blue' },
      { label: 'Файлов чеков', count: summary.files, icon: FileText, tone: 'pink' },
      { label: 'Ссылок', count: summary.links, icon: LinkIcon, tone: 'orange' },
      { label: 'Без материалов', count: summary.missing, icon: Paperclip, tone: 'neutral' },
    ].map(({ label, count, icon: Icon, tone }) => <div key={label} data-tone={tone}><span className="receipt-summary-icon" aria-hidden="true"><Icon size={21}/></span><div><dt>{label}</dt><dd>{countLabel(count)}</dd></div></div>)}
  </dl>
}

function ReceiptAttachmentRow({ attachment }: { attachment: ReceiptAttachment }) {
  const href = normalizeReceiptUrl(attachment.url)
  const host = receiptHostname(attachment.url)
  const size = receiptFileSize(attachment.size_bytes)
  const Icon = attachment.kind === 'file' ? FileText : LinkIcon
  const content = <>
    <span className="receipt-attachment-icon" aria-hidden="true"><Icon size={20}/></span>
    <span className="receipt-attachment-copy"><strong>{attachment.label || attachment.file_name || (attachment.kind === 'file' ? 'Файл чека' : 'Ссылка к платежу')}</strong><span>{attachment.kind === 'file' ? [attachment.file_name, size].filter(Boolean).join(' · ') || 'Файл' : host || 'Ссылка'}{!href && ' · Недоступна'}</span></span>
    <span className="receipt-attachment-kind">{attachment.kind === 'file' ? 'Файл' : 'Ссылка'}</span>
    {href && <ArrowUpRight size={17} className="receipt-attachment-arrow" aria-hidden="true"/>}
  </>
  return href ? <a className="receipt-attachment" data-kind={attachment.kind} href={href} target="_blank" rel="noopener noreferrer" aria-label={`${attachment.label || attachment.file_name || (attachment.kind === 'file' ? 'Файл чека' : 'Ссылка к платежу')}, открыть в новой вкладке`}>{content}</a>
    : <div className="receipt-attachment receipt-attachment-unavailable" data-kind={attachment.kind}>{content}</div>
}

/** A controlled view: URL state, fetching and pagination are handled by its parent. */
export function ReceiptsPanel({ items, loading, error, onRetry, filters, onFiltersChange, total, limit, offset, onPage, summary, summaryLoading = false, summaryError, onSummaryRetry, onEdit, onOpenPayment, eyebrow = 'Рабочее пространство' }: ReceiptsPanelProps) {
  const id = useId()
  const filtered = Boolean(filters.query || filters.currency || filters.kind !== 'all')
  return <section className="receipts-page">
    <PageHeader kind="receipts" title="Чеки и ссылки" eyebrow={eyebrow} description="Документы и ссылки собраны рядом с платежами. Легко найти нужное подтверждение и вернуться к его периоду."/>
    {!loading && !error && !summaryLoading && !summaryError && summary && <ReceiptSummaryCards summary={summary}/>}
    {summaryLoading && !error && <div className="receipts-summary-loading" role="status"><span className="spinner" aria-hidden="true"/>Загружаем сводку материалов…</div>}
    {summaryError && !error ? <div className="receipts-summary-error"><ErrorNotice error={summaryError} onRetry={onSummaryRetry}/></div> : null}
    <section className="panel receipts-panel" aria-labelledby={`receipts-list-heading-${id}`}>
      <div className="section-head"><div><h2 id={`receipts-list-heading-${id}`}>Материалы платежей{!loading && !error && total !== null && <span className="section-count">{countLabel(total)}</span>}</h2><p>Файлы и ссылки открываются в отдельной вкладке.</p></div><button className="icon-button" type="button" aria-label="Обновить чеки и ссылки" disabled={loading} onClick={onRetry}><RefreshCw size={17}/></button></div>
      <form className="receipts-filters" onSubmit={event => event.preventDefault()} aria-label="Фильтры чеков и ссылок">
        <div className="field receipts-search"><label htmlFor={`receipt-search-${id}`}>Найти платёж или материал</label><div className="receipt-search-input"><Search size={17} aria-hidden="true"/><input id={`receipt-search-${id}`} type="search" value={filters.query} onChange={event => onFiltersChange({ ...filters, query: event.target.value })} placeholder="Название платежа, файла или ссылки" autoComplete="off"/></div></div>
        <div className="field"><label htmlFor={`receipt-currency-${id}`}>Валюта</label><SelectField id={`receipt-currency-${id}`} value={filters.currency} onChange={currency => onFiltersChange({ ...filters, currency: currency as ReceiptFilters['currency'] })} options={currencyOptions}/></div>
        <div className="field"><label htmlFor={`receipt-kind-${id}`}>Тип материала</label><SelectField id={`receipt-kind-${id}`} value={filters.kind} onChange={kind => onFiltersChange({ ...filters, kind: kind as ReceiptFilters['kind'] })} options={kindOptions}/></div>
        <button type="button" className="btn btn-danger receipts-reset" onClick={() => onFiltersChange(defaultReceiptFilters())}>Сбросить</button>
      </form>
      {loading ? <div className="receipts-loading" role="status" aria-label="Загрузка чеков и ссылок">{[1, 2, 3].map(index => <div className="skeleton" key={index}/>)}</div> : error ? <div className="receipts-load-error"><ErrorNotice error={error} onRetry={onRetry}/></div> : items.length === 0 ? <EmptyState title={filtered ? 'Материалы не найдены' : 'Пока нет чеков и ссылок'}>{filtered ? 'Попробуйте изменить запрос, валюту или тип материала.' : 'Материалы появятся здесь после добавления к платежам.'}</EmptyState> : <div className="receipts-list">
        {items.map(entry => <article className="receipt-entry" key={entry.id}>
          <div className="receipt-entry-top"><span className="receipt-entry-symbol" aria-hidden="true"><ReceiptText size={24}/></span><div className="receipt-entry-heading"><h3>{entry.title}</h3><div className="receipt-entry-dates"><span>Срок <time dateTime={entry.due_date}>{dateLabel(entry.due_date)}</time></span>{entry.paid_on && <span>Оплачено <time dateTime={entry.paid_on}>{dateLabel(entry.paid_on)}</time></span>}</div></div><div className="receipt-entry-amount"><strong>{money(entry.amount, entry.currency)}</strong><span>{entry.currency}</span></div></div>
          {entry.attachments.length ? <div className="receipt-attachments" aria-label={`Материалы платежа «${entry.title}»`}>{entry.attachments.map(attachment => <ReceiptAttachmentRow key={attachment.id} attachment={attachment}/>)}</div> : <p className="receipt-entry-empty"><Paperclip size={17} aria-hidden="true"/>К этому периоду материалы ещё не добавлены.</p>}
          {(onOpenPayment || (onEdit && entry.can_edit)) && <div className="receipt-entry-actions">{onOpenPayment && <button type="button" className="receipt-payment-link" onClick={() => onOpenPayment(entry.occurrence_id)}>Открыть платёж<ArrowUpRight size={15} aria-hidden="true"/></button>}{onEdit && entry.can_edit && <button className="btn btn-secondary btn-small" type="button" onClick={() => onEdit(entry)}><PencilLine size={15} aria-hidden="true"/>{entry.attachments.length ? 'Изменить материалы' : 'Добавить материал'}</button>}</div>}
        </article>)}
      </div>}
      {!loading && !error && total !== null && <Pagination total={total} limit={limit} offset={offset} onPage={onPage}/>}
    </section>
  </section>
}

export interface LinkReceiptValues { url: string; label: string }
export interface LinkReceiptFormProps {
  initialValues?: Partial<LinkReceiptValues>
  onSave: (values: LinkReceiptValues) => Promise<void>
  onSaved?: () => void
  onCancel?: () => void
  onBusyChange?: (busy: boolean) => void
  disabled?: boolean
}
type LinkFields = Partial<Record<'url' | 'label', string>>

/** Presentational form only. Mutation transport and success refresh belong to the caller. */
export function LinkReceiptForm({ initialValues, onSave, onSaved, onCancel, onBusyChange, disabled = false }: LinkReceiptFormProps) {
  const id = useId()
  const [url, setUrl] = useState(initialValues?.url || '')
  const [label, setLabel] = useState(initialValues?.label || '')
  const [fields, setFields] = useState<LinkFields>({})
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const [uncertain, setUncertain] = useState(false)
  const guard = useRef(false)
  const mounted = useRef(false)
  const urlInput = useRef<HTMLInputElement>(null)
  const labelInput = useRef<HTMLInputElement>(null)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  function revealFields(next: LinkFields) {
    setFields(next)
    requestAnimationFrame(() => {
      if (!mounted.current) return
      if (next.url) urlInput.current?.focus()
      else if (next.label) labelInput.current?.focus()
    })
  }
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (guard.current || busy || disabled || uncertain) return
    const normalized = normalizeReceiptUrl(url)
    setError(null)
    if (!normalized) { revealFields({ url: 'Укажите полную ссылку с http:// или https://, без логина и пароля.' }); return }
    guard.current = true; setBusy(true); setFields({}); onBusyChange?.(true)
    try {
      // A timed-out create is never replayed by the form.
      await onSave({ url: normalized, label: label.trim() })
      if (mounted.current) onSaved?.()
    } catch (reason) {
      if (!mounted.current) return
      const apiError = reason instanceof ApiError ? reason : null
      if (apiError?.status === 401) return
      const next: LinkFields = {}
      for (const detail of apiError?.details || []) {
        const name = detail.field.replace(/^body\./, '')
        if (name === 'url' || name === 'label') next[name] = detail.message
      }
      revealFields(next)
      if (apiError?.status === 0 || (apiError?.code === 'INVALID_RESPONSE' && apiError.status >= 200 && apiError.status < 300)) setUncertain(true)
      setError(reason)
    } finally { guard.current = false; if (mounted.current) setBusy(false); onBusyChange?.(false) }
  }
  const blocked = busy || disabled || uncertain
  return <form className="receipt-link-form" onSubmit={event => void submit(event)} noValidate>
    <div className="receipt-link-intro"><span aria-hidden="true"><LinkIcon size={24}/></span><div><h3>Ссылка к платежу</h3><p>Чек, счёт или страница с деталями — рядом с нужным периодом.</p></div></div>
    <div className="field"><label htmlFor={`receipt-url-${id}`}>Адрес ссылки</label><input ref={urlInput} id={`receipt-url-${id}`} type="url" inputMode="url" autoComplete="off" autoCapitalize="none" spellCheck={false} value={url} disabled={blocked} onChange={event => { setUrl(event.target.value); setFields(value => ({ ...value, url: undefined })) }} placeholder="https://example.com/receipt" required aria-invalid={Boolean(fields.url)} aria-describedby={fields.url ? `receipt-url-error-${id}` : `receipt-url-hint-${id}`}/>{fields.url ? <p className="field-error" id={`receipt-url-error-${id}`}>{fields.url}</p> : <p className="field-hint" id={`receipt-url-hint-${id}`}>Только полные ссылки с http:// или https://.</p>}</div>
    <div className="field"><label htmlFor={`receipt-label-${id}`}>Название <span className="muted">· необязательно</span></label><input ref={labelInput} id={`receipt-label-${id}`} autoComplete="off" value={label} disabled={blocked} onChange={event => { setLabel(event.target.value); setFields(value => ({ ...value, label: undefined })) }} placeholder="Например, чек за октябрь" aria-invalid={Boolean(fields.label)} aria-describedby={fields.label ? `receipt-label-error-${id}` : undefined}/>{fields.label && <p className="field-error" id={`receipt-label-error-${id}`}>{fields.label}</p>}</div>
    <div className="notice receipt-link-note"><Info size={18} aria-hidden="true"/><p>Открытие ссылки само по себе не меняет статус оплаты.</p></div>
    {error ? <ErrorNotice error={error}/> : null}
    {uncertain && <p className="receipt-link-uncertain" role="alert"><AlertCircle size={18} aria-hidden="true"/>Результат сохранения пока неизвестен. Закройте форму и обновите список перед новой попыткой.</p>}
    <div className="receipt-link-actions"><button type="submit" className="btn btn-primary" disabled={blocked}>{busy ? <span className="spinner" aria-hidden="true"/> : <Check size={17} aria-hidden="true"/>}{busy ? 'Сохраняем…' : 'Сохранить ссылку'}</button>{onCancel && <button type="button" className="btn btn-secondary" disabled={busy} onClick={onCancel}>{uncertain ? 'Закрыть и проверить' : 'Отмена'}</button>}</div>
  </form>
}
