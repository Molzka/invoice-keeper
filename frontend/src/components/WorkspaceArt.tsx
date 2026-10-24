import { CalendarDays, LayoutList, ListChecks, ReceiptText, Repeat2, Users, Wallet } from './BrandIcons'

export type WorkspaceArtKind = 'payments' | 'recurring' | 'history' | 'users' | 'calendar' | 'activity' | 'budget' | 'receipts'
const icons = { payments: LayoutList, recurring: Repeat2, history: ReceiptText, users: Users, calendar: CalendarDays, activity: ListChecks, budget: Wallet, receipts: ReceiptText }

/** Shared framing with a distinct set of softly curved routes for each section. */
const patterns: Record<WorkspaceArtKind, { lines: string; accent: string; details: [string, string] }> = {
  payments: {
    details: ['M4 149h158c27 0 43-15 43-42V75c0-19 10-29 29-29h162', 'M4 18h76c22 0 34 12 34 34v15c0 22 12 34 34 34h92'],
    lines: 'M4 55h392M4 79h392M4 103h392',
    accent: 'M4 132h148c24 0 36-12 36-36V66c0-24 12-36 36-36h172',
  },
  calendar: {
    details: ['M4 160h220c27 0 41-14 41-41V8', 'M4 26h58c24 0 36 12 36 36v36c0 24 12 36 36 36h76'],
    lines: 'M140 8v164M164 8v164M188 8v164',
    accent: 'M4 143h208c24 0 36-12 36-36V8',
  },
  recurring: {
    details: ['M4 88h140c25 0 39 14 39 39v8c0 14 8 22 22 22h191', 'M4 12h56c24 0 36 12 36 36v8c0 24 12 36 36 36h108'],
    lines: 'M4 30h392M4 54h392M4 78h392',
    accent: 'M4 104h128c24 0 36 12 36 36v4c0 18 10 28 28 28h200',
  },
  history: {
    details: ['M130 8v55c0 22 12 34 34 34h232', 'M4 154h156c22 0 34-12 34-34v-24c0-22 12-34 34-34h36'],
    lines: 'M32 8v164M56 8v164M80 8v164',
    accent: 'M112 8v68c0 24 12 36 36 36h248',
  },
  users: {
    details: ['M4 163h154c28 0 42-14 42-42V51c0-17 10-27 27-27h169', 'M4 12h66c22 0 34 12 34 34v16c0 22 12 34 34 34h100'],
    lines: 'M4 34l238 138M4 62l190 110M4 90l142 82',
    accent: 'M4 146h142c24 0 36-12 36-36V44c0-24 12-36 36-36h178',
  },
  activity: {
    details: ['M22 8v96c0 23 12 35 35 35h339', 'M4 50h52c24 0 36 12 36 36v28c0 24 12 36 36 36h100'],
    lines: 'M104 8v164M128 8v164M152 8v164',
    accent: 'M4 8v108c0 24 12 36 36 36h356',
  },
  budget: {
    details: ['M4 75h88c23 0 35-12 35-35v-3c0-18 10-28 28-28h42', 'M4 153h190c24 0 36-12 36-36V76c0-24 12-36 36-36h130'],
    lines: 'M4 118h392M4 142h392M4 166h392',
    accent: 'M4 92h100c24 0 36-12 36-36V44c0-24 12-36 36-36h220',
  },
  receipts: {
    details: ['M4 49h95c21 0 32 11 32 32v48c0 20 11 31 31 31h234', 'M36 8v64c0 22 12 34 34 34h164'],
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
      <path className="brand-pattern-accent brand-pattern-detail" d={pattern.details[0]} strokeWidth="2" strokeLinecap="round" pathLength="1"/>
      <path className="brand-pattern-accent brand-pattern-detail brand-pattern-detail--contrast" d={pattern.details[1]} strokeWidth="2.5" strokeLinecap="round" pathLength="1"/>
      <path className="brand-pattern-accent" d={pattern.accent} strokeWidth="4" strokeLinecap="round" pathLength="1"/>
    </svg>
    <span className="brand-section-symbol"><Icon size={40} className="brand-section-icon"/></span>
  </div>
}
