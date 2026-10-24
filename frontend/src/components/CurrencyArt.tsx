import { useId } from 'react'
import type { Currency } from '../types/api'

const symbols: Record<Currency, string> = {
  RUB: 'M46 100V30H69C97 30 97 66 69 66H36M36 80H73',
  USD: 'M85 39C78 28 49 25 44 42C38 65 89 58 85 81C82 100 51 104 39 89M62 20V111',
  EUR: 'M91 36C64 14 32 35 32 65C32 98 65 116 91 95M22 56H75M22 75H69',
}

export function CurrencyArt({ currency }: { currency: Currency }) {
  const id = `currency-${useId().replace(/:/g, '')}`
  return <svg className="currency-art" viewBox="0 0 154 154" fill="none" aria-hidden="true" focusable="false">
    <defs>
      <radialGradient id={`${id}-halo`}><stop stopColor="var(--currency-accent)" stopOpacity=".16"/><stop offset="1" stopColor="var(--currency-accent)" stopOpacity="0"/></radialGradient>
      <linearGradient id={`${id}-paper`} x1="37" y1="20" x2="120" y2="141" gradientUnits="userSpaceOnUse"><stop stopColor="white"/><stop offset="1" stopColor="var(--currency-soft)"/></linearGradient>
    </defs>
    <circle cx="83" cy="77" r="70" fill={`url(#${id}-halo)`}/>
    <ellipse cx="83" cy="137" rx="46" ry="5" fill="var(--currency-accent)" opacity=".06"/>
    <path className="currency-art-orbit" d="M126 20C142 34 146 59 141 81M29 136C13 128 7 111 10 95" stroke="var(--currency-accent)" strokeWidth="1" strokeDasharray="2 6" strokeLinecap="round"/>
    <g className="currency-art-plate">
      <rect x="49" y="23" width="75" height="112" rx="18" transform="rotate(12 86 79)" fill="var(--currency-soft)" stroke="var(--currency-line)"/>
      <g transform="rotate(-7 79 78)">
        <rect x="32" y="14" width="91" height="124" rx="20" fill={`url(#${id}-paper)`} stroke="var(--currency-line)"/>
        <rect x="38" y="20" width="79" height="112" rx="15" stroke="white" strokeOpacity=".9"/>
        <path className="currency-art-symbol" d={symbols[currency]} transform="translate(14 6)" stroke="var(--currency-accent)" strokeWidth="2.3" strokeLinecap="round" strokeLinejoin="round"/>
      </g>
    </g>
    <g className="currency-art-spark" stroke="var(--currency-accent)" strokeLinecap="round">
      <circle cx="127" cy="113" r="10" fill="white" stroke="var(--currency-line)"/>
      <path d="M127 109v8M123 113h8M18 54v6M15 57h6" strokeWidth="1.3"/>
      <circle cx="133" cy="38" r="2" fill="var(--currency-accent)" stroke="none"/>
    </g>
  </svg>
}
