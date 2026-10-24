import { BarChart3, CalendarDays, CreditCard, History, ReceiptText, Repeat2, ShieldCheck, Users } from './BrandIcons'

export type WorkspaceArtKind = 'payments' | 'recurring' | 'history' | 'users' | 'calendar' | 'activity' | 'budget' | 'receipts'
const icons = { payments: CreditCard, recurring: Repeat2, history: History, users: Users, calendar: CalendarDays, activity: ShieldCheck, budget: BarChart3, receipts: ReceiptText }

/** Routes span the entire header; their quiet lower edge keeps the copy clear. */
const patterns: Record<WorkspaceArtKind, { lines: string; accent: string; details: [string, string] }> = {
  payments: {
    lines: 'M0 218h690c38 0 56-18 56-56v-40c0-38 18-56 56-56h398M0 234h706c38 0 56-18 56-56v-40c0-38 18-56 56-56h382M0 250h722c38 0 56-18 56-56v-40c0-38 18-56 56-56h366',
    accent: 'M0 205h640c40 0 60-20 60-60V96c0-40 20-60 60-60h440',
    details: ['M0 242h654c40 0 60-20 60-60v-40c0-40 20-60 60-60h426', 'M1200 176H940c-34 0-52-18-52-52V72c0-34-18-52-52-52H660'],
  },
  calendar: {
    lines: 'M0 218h734c32 0 48-16 48-48V76c0-32 16-48 48-48h370M0 234h750c32 0 48-16 48-48V92c0-32 16-48 48-48h354M0 250h766c32 0 48-16 48-48v-94c0-32 16-48 48-48h338',
    accent: 'M0 206h676c38 0 58-20 58-58V8',
    details: ['M0 242h710c38 0 58-20 58-58V8', 'M1200 192H960c-36 0-54-18-54-54V80c0-36-18-54-54-54H620'],
  },
  recurring: {
    lines: 'M0 218h588c42 0 62-20 62-62v-34c0-42 20-62 62-62h488M0 234h604c42 0 62-20 62-62v-34c0-42 20-62 62-62h472M0 250h620c42 0 62-20 62-62v-34c0-42 20-62 62-62h456',
    accent: 'M0 204h568c38 0 58-20 58-58v-40c0-38 20-58 58-58h516',
    details: ['M0 242h632c40 0 60-20 60-60v-32c0-40 20-60 60-60h448', 'M630 12h150c36 0 54 18 54 54v56c0 36 18 54 54 54h312'],
  },
  history: {
    lines: 'M0 218h800c38 0 56-18 56-56V8M0 234h816c38 0 56-18 56-56V8M0 250h832c38 0 56-18 56-56V8',
    accent: 'M0 204h726c38 0 58-20 58-58V70c0-38 20-58 58-58h358',
    details: ['M0 240h748c38 0 58-20 58-58v-56c0-38 20-58 58-58h336', 'M1200 196H988c-40 0-60-20-60-60V92c0-40-20-60-60-60H658'],
  },
  users: {
    lines: 'M0 218h624c42 0 62-20 62-62v-26c0-42 20-62 62-62h452M0 234h640c42 0 62-20 62-62v-26c0-42 20-62 62-62h436M0 250h656c42 0 62-20 62-62v-26c0-42 20-62 62-62h420',
    accent: 'M0 204h602c40 0 60-20 60-60v-48c0-40 20-60 60-60h478',
    details: ['M0 242h664c38 0 58-20 58-58v-36c0-38 20-58 58-58h420', 'M1200 202h-166c-42 0-62-20-62-62V76c0-42-20-62-62-62H718'],
  },
  activity: {
    lines: 'M0 218h780c34 0 50-16 50-50V8M0 234h796c34 0 50-16 50-50V8M0 250h812c34 0 50-16 50-50V8',
    accent: 'M0 204h668c40 0 60-20 60-60V90c0-40 20-60 60-60h412',
    details: ['M0 242h704c38 0 58-20 58-58v-40c0-38 20-58 58-58h380', 'M1200 198H982c-42 0-62-20-62-62V82c0-42-20-62-62-62H660'],
  },
  budget: {
    lines: 'M0 218h690c42 0 62-20 62-62v-18c0-42 20-62 62-62h386M0 234h706c42 0 62-20 62-62v-18c0-42 20-62 62-62h370M0 250h722c42 0 62-20 62-62v-18c0-42 20-62 62-62h354',
    accent: 'M0 204h634c40 0 60-20 60-60V72c0-40 20-60 60-60h446',
    details: ['M0 242h666c38 0 58-20 58-58V96c0-38 20-58 58-58h418', 'M1200 184H978c-36 0-54-18-54-54V92c0-36-18-54-54-54H698'],
  },
  receipts: {
    lines: 'M0 218h754c36 0 54-18 54-54V8M0 234h770c36 0 54-18 54-54V8M0 250h786c36 0 54-18 54-54V8',
    accent: 'M0 204h646c38 0 58-20 58-58v-40c0-38 20-58 58-58h438',
    details: ['M0 242h680c38 0 58-20 58-58v-32c0-38 20-58 58-58h404', 'M1200 188H970c-38 0-58-20-58-58V78c0-38-20-58-58-58H654'],
  },
}

export function WorkspaceArt({ kind, className = '' }: { kind: WorkspaceArtKind; className?: string }) {
  const Icon = icons[kind]
  const pattern = patterns[kind]
  return <div className={`workspace-art workspace-art--${kind} ${className}`} aria-hidden="true">
    <svg className="workspace-art-pattern" viewBox="0 0 1200 260" preserveAspectRatio="none" fill="none" focusable="false">
      <path className="brand-pattern-lines" d={pattern.lines} stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" vectorEffect="non-scaling-stroke"/>
      <path className="brand-pattern-accent brand-pattern-detail" d={pattern.details[0]} strokeWidth="1.5" strokeLinecap="round" vectorEffect="non-scaling-stroke" pathLength="1"/>
      <path className="brand-pattern-accent brand-pattern-detail brand-pattern-detail--contrast" d={pattern.details[1]} strokeWidth="2" strokeLinecap="round" vectorEffect="non-scaling-stroke" pathLength="1"/>
      <path className="brand-pattern-accent" d={pattern.accent} strokeWidth="3" strokeLinecap="round" vectorEffect="non-scaling-stroke" pathLength="1"/>
    </svg>
    <span className="brand-section-symbol"><Icon size={42} className="brand-section-icon"/></span>
  </div>
}
