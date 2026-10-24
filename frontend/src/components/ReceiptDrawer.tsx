import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { api, ApiError } from '../api/client'
import type { PaymentOccurrence } from '../types/api'
import type { PaymentReceipt } from '../types/extras'
import { normalizeReceiptUrl, receiptFileSize } from '../lib/receipt-links'
import { Drawer, ErrorNotice } from './UI'
import { Download, Paperclip, Trash2 } from './BrandIcons'

export function ReceiptDrawer({ item, onClose, onChanged }: { item: PaymentOccurrence; onClose: () => void; onChanged: () => void }) {
  const [receipt, setReceipt] = useState<PaymentReceipt | null>(null)
  const [loading, setLoading] = useState(true)
  const [kind, setKind] = useState<'link' | 'file'>('link')
  const [url, setUrl] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [fieldError, setFieldError] = useState('')
  const [busy, setBusy] = useState(false)
  const [uncertain, setUncertain] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [retry, setRetry] = useState(0)
  const guard = useRef(false)
  useEffect(() => {
    let alive = true
    setLoading(true); setError(null)
    api.getReceipt(item.id).then(value => { if (alive) { setReceipt(value); setUncertain(false); setUrl(value?.url || ''); setKind(value?.kind || 'link') } }).catch(reason => { if (alive) setError(reason) }).finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [item.id, retry])
  async function mutate(remove = false) {
    if (guard.current || loading || uncertain || item.is_cancelled) return
    setFieldError(''); setError(null)
    let normalized: string | null = null
    if (!remove && kind === 'link') {
      normalized = normalizeReceiptUrl(url.trim())
      if (!normalized || !normalized.startsWith('https://') || normalized.length > 2048) { setFieldError('Укажите HTTPS-ссылку без логина и пароля, до 2048 символов.'); return }
    }
    if (!remove && kind === 'file' && (!file || !['application/pdf','image/png','image/jpeg'].includes(file.type) || file.size < 1 || file.size > 5 * 1024 * 1024)) { setFieldError('Выберите PDF, PNG или JPEG размером до 5 МиБ.'); return }
    guard.current = true; setBusy(true)
    try {
      if (remove) { await api.deleteReceipt(item.id); setReceipt(null); setUrl(''); setFile(null) }
      else setReceipt(kind === 'link' ? await api.saveReceiptLink(item.id, normalized!) : await api.saveReceiptFile(item.id, file!))
      setConfirmDelete(false); onChanged()
    } catch (reason) {
      setError(reason)
      if (reason instanceof ApiError) { setFieldError(reason.details.map(detail => detail.message).join(' ')); setUncertain(reason.status === 0 || reason.status >= 500 || reason.code === 'INVALID_RESPONSE') }
    } finally { guard.current = false; setBusy(false) }
  }
  async function download() {
    if (guard.current) return
    guard.current = true; setBusy(true); setError(null)
    try {
      const blob = await api.downloadReceipt(item.id)
      const href = URL.createObjectURL(blob)
      const anchor = document.createElement('a'); anchor.href = href; anchor.download = receipt?.filename || 'receipt'; anchor.click()
      setTimeout(() => URL.revokeObjectURL(href), 60000)
    } catch (reason) { setError(reason) }
    finally { guard.current = false; setBusy(false) }
  }
  const href = receipt?.kind === 'link' ? normalizeReceiptUrl(receipt.url || '') : null
  const disabled = busy || loading || uncertain || Boolean(item.is_cancelled)
  return <Drawer title="Чек или ссылка" subtitle={item.title} canClose={!busy} onClose={onClose}>
    {loading ? <p className="loading-state" role="status"><span className="spinner"/>Загружаем подтверждение…</p> : <>
      {receipt && <section className="receipt-current notice"><Paperclip size={20}/><div><strong>{receipt.kind === 'file' ? receipt.filename : 'Ссылка к платежу'}</strong><p>{receipt.kind === 'file' ? receiptFileSize(receipt.size_bytes ?? undefined) : receipt.url}</p>{href && <a href={href} target="_blank" rel="noopener noreferrer" className="btn btn-secondary btn-small">Открыть ссылку</a>}{receipt.kind === 'file' && <button type="button" className="btn btn-secondary btn-small" disabled={busy} onClick={() => void download()}><Download size={16}/>Скачать файл</button>}</div></section>}
      {!receipt && !error && <p className="muted">К этому периоду ещё не прикреплено подтверждение.</p>}
      {item.is_cancelled ? <p className="notice">Удалённый период: материалы доступны только для просмотра.</p> : <form className="form-grid" onSubmit={(event: FormEvent) => { event.preventDefault(); void mutate() }} noValidate>
        <p className="field-hint">К периоду можно прикрепить один файл или HTTPS-ссылку. Новое подтверждение заменит предыдущее.</p>
        <div className="segmented" role="group" aria-label="Тип подтверждения"><button className="segment" type="button" aria-pressed={kind === 'link'} disabled={disabled} onClick={() => { setKind('link'); setFieldError('') }}>Ссылка</button><button className="segment" type="button" aria-pressed={kind === 'file'} disabled={disabled} onClick={() => { setKind('file'); setFieldError('') }}>Файл</button></div>
        {kind === 'link' ? <label className="field"><span>HTTPS-ссылка</span><input type="url" value={url} onChange={event => setUrl(event.target.value)} placeholder="https://…" maxLength={2048} disabled={disabled} aria-invalid={Boolean(fieldError)} aria-describedby="receipt-input-error"/></label> : <label className="field"><span>PDF, PNG или JPEG до 5 МиБ</span><input type="file" accept="application/pdf,image/png,image/jpeg" onChange={event => setFile(event.target.files?.[0] || null)} disabled={disabled} aria-invalid={Boolean(fieldError)} aria-describedby="receipt-input-error"/></label>}
        {fieldError && <p className="field-error" id="receipt-input-error" role="alert">{fieldError}</p>}
        <div className="form-actions"><button className="btn btn-primary" type="submit" disabled={disabled}>{busy ? 'Сохраняем…' : receipt ? 'Заменить подтверждение' : 'Прикрепить'}</button>{receipt && <button className="btn btn-danger" type="button" disabled={disabled} onClick={() => setConfirmDelete(true)}><Trash2 size={16}/>Удалить</button>}</div>
        {confirmDelete && <div className="notice" role="group" aria-label="Подтверждение удаления чека"><p>Удалить прикреплённое подтверждение? Платёж и отметка оплаты сохранятся.</p><div className="form-actions"><button type="button" className="btn btn-secondary" disabled={busy} onClick={() => setConfirmDelete(false)}>Оставить</button><button type="button" className="btn btn-danger" disabled={disabled} onClick={() => void mutate(true)}>Удалить подтверждение</button></div></div>}
      </form>}
    </>}
    {error != null && <ErrorNotice error={error} onRetry={!uncertain && !busy ? () => setRetry(value => value + 1) : undefined}/>}
    {uncertain && <div className="notice" role="status"><p>Результат изменения неизвестен. Сначала проверьте подтверждение на сервере.</p><button className="btn btn-secondary" type="button" onClick={() => { setRetry(value => value + 1); onChanged() }}>Проверить состояние</button></div>}
  </Drawer>
}
