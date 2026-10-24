import type { Currency } from '../types/api'

const symbols: Record<Currency, string> = {
  RUB: 'M46 100V30H69C97 30 97 66 69 66H36M36 80H73',
  USD: 'M85 39C78 28 49 25 44 42C38 65 89 58 85 81C82 100 51 104 39 89M62 20V111',
  EUR: 'M91 36C64 14 32 35 32 65C32 98 65 116 91 95M22 56H75M22 75H69',
}

export function CurrencyArt({ currency }: { currency: Currency }) {
  return <svg className="currency-art" viewBox="0 0 130 132" fill="none" aria-hidden="true" focusable="false">
    <path className="currency-art-orbit" d="M100 17C114 28 121 45 119 64M24 113C12 102 7 89 8 75" stroke="currentColor" strokeWidth="1" strokeDasharray="2 6" strokeLinecap="round"/>
    <path className="currency-art-symbol" d={symbols[currency]} stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
    <path d="M112 83V91M108 87H116M16 40V46M13 43H19" stroke="currentColor" strokeWidth="1" strokeLinecap="round"/>
  </svg>
}
