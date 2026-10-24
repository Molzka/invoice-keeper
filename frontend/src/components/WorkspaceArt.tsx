import { CalendarDays, LayoutList, ListChecks, ReceiptText, Repeat2, Users, Wallet } from './BrandIcons'

export type WorkspaceArtKind = 'payments' | 'recurring' | 'history' | 'users' | 'calendar' | 'activity' | 'budget' | 'receipts'
const icons = { payments: LayoutList, recurring: Repeat2, history: ReceiptText, users: Users, calendar: CalendarDays, activity: ListChecks, budget: Wallet, receipts: ReceiptText }

/** Each section keeps the same frame, while the four-line route has its own geometry. */
const patterns: Record<WorkspaceArtKind, { lines: string; accent: string }> = {
  payments: {
    lines: 'M4 55h392M4 79h392M4 103h392',
    accent: 'M4 132h148c24 0 36-12 36-36V66c0-24 12-36 36-36h172',
  },
  calendar: {
    lines: 'M140 8v164M164 8v164M188 8v164',
    accent: 'M4 143h208c24 0 36-12 36-36V8',
  },
  recurring: {
    lines: 'M4 30h392M4 54h392M4 78h392',
    accent: 'M4 104h128c24 0 36 12 36 36v4c0 18 10 28 28 28h200',
  },
  history: {
    lines: 'M32 8v164M56 8v164M80 8v164',
    accent: 'M112 8v68c0 24 12 36 36 36h248',
  },
  users: {
    lines: 'M4 34l238 138M4 62l190 110M4 90l142 82',
    accent: 'M4 146h142c24 0 36-12 36-36V44c0-24 12-36 36-36h178',
  },
  activity: {
    lines: 'M104 8v164M128 8v164M152 8v164',
    accent: 'M4 8v108c0 24 12 36 36 36h356',
  },
  budget: {
    lines: 'M4 118h392M4 142h392M4 166h392',
    accent: 'M4 92h100c24 0 36-12 36-36V44c0-24 12-36 36-36h220',
  },
  receipts: {
    lines: 'M188 8v164M212 8v164M236 8v164',
    accent: 'M4 32h108c24 0 36 12 36 36v68c0 24 12 36 36 36h212',
  },
}

export function WorkspaceArt({ kind, className = '' }: { kind: WorkspaceArtKind; className?: string }) {
  const Icon = icons[kind]
  const pattern = patterns[kind]
  return <div className={`workspace-art workspace-art--${kind} ${className}`} aria-hidden="true">
    <svg className="workspace-art-pattern" viewBox="0 0 400 180" preserveAspectRatio="xMidYMid meet" fill="none" focusable="false">
      <path className="brand-pattern-lines" d={pattern.lines} stroke="currentColor" strokeWidth="3" strokeLinecap="round"/>
      <path className="brand-pattern-accent" d={pattern.accent} strokeWidth="4" strokeLinecap="round" pathLength="1"/>
    </svg>
    <span className="brand-section-symbol"><Icon size={40} className="brand-section-icon"/></span>
  </div>
}
