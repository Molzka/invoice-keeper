import type { Currency } from '../types/api'
const symbols: Record<Currency, string> = { RUB: '₽', USD: '$', EUR: '€' }

export function CurrencyArt({ currency }: { currency: Currency }) {
  return <svg className="currency-art" viewBox="0 0 154 154" aria-hidden="true" focusable="false">
    <g className="currency-art-plate">
      <rect x="25" y="12" width="112" height="124" rx="30" fill="var(--currency-soft)"/>
      <g fill="none" stroke="var(--currency-accent)" strokeWidth="2" strokeLinecap="round" opacity=".35"><path d="M4 107h146M4 115h146M4 123h146"/><path d="M4 131h30c10 0 14-4 14-14V99c0-10 4-14 14-14h88"/></g>
      <text className="currency-art-symbol" x="81" y="101" textAnchor="middle" fill="var(--currency-accent)" fontFamily="Exo 2, sans-serif" fontSize="92" fontWeight="700">{symbols[currency]}</text>
    </g>
  </svg>
}
