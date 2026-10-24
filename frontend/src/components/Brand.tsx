import { useState } from 'react'
import type { CSSProperties } from 'react'
import { ReceiptText } from './BrandIcons'

/** The approved keycap stays fixed; the receipt is a separate application badge. */
export function BrandMark({ size = 52 }: { size?: number }) {
  return <span className="brand-emblem" style={{ '--brand-mark-size': size + 'px' } as CSSProperties} aria-hidden="true">
    <img className="brand-mark brand-mark-light" src="/brand/aeza-mark-light-on-dark.png" width={size} height={size} alt=""/>
    <img className="brand-mark brand-mark-dark" src="/brand/aeza-mark-dark-on-light.png" width={size} height={size} alt=""/>
    <span className="brand-receipt-badge"><ReceiptText size={12}/></span>
  </span>
}
export function Brand({ onHome }: { onHome?: () => void }) {
  const [open, setOpen] = useState(false)
  return <button type="button" className="brand-logo" data-open={open} aria-label="Invoice Keeper — главная" onClick={() => { if (window.matchMedia('(hover: none)').matches && !open) setOpen(true); else onHome?.() }} onBlur={() => setOpen(false)}>
    <BrandMark/>
    <span className="brand-name" aria-hidden="true"><span className="brand-word">Invoice</span><span className="brand-word">Keeper<span className="brand-name-dot">.</span></span></span>
  </button>
}
