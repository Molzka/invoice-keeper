import { getWorkspacePattern } from '../lib/workspace-patterns'

export type WorkspaceArtKind = 'payments' | 'recurring' | 'history' | 'users' | 'calendar' | 'activity' | 'budget' | 'receipts'

// Exact guide assets are selected per section rather than substituting an icon font.
const sectionIcons: Record<WorkspaceArtKind, string> = {
  payments: 'credit-card', calendar: 'hourglass', recurring: 'flag', history: 'note-pencil',
  users: 'users', activity: 'shield', budget: 'chart', receipts: 'bag',
}

export function WorkspaceArt({ kind, className = '', copyEdge }: { kind: WorkspaceArtKind; className?: string; copyEdge: number | null }) {
  const { routes, guides } = getWorkspacePattern(kind, copyEdge ?? 1600)
  return <div className={`workspace-art workspace-art--${kind} ${className}`} aria-hidden="true">
    <svg className="workspace-art-pattern" style={{ visibility: copyEdge === null ? 'hidden' : undefined }} viewBox="0 0 1600 320" preserveAspectRatio="none" fill="none" focusable="false">
      <path className="brand-pattern-lines" d={guides} stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" vectorEffect="non-scaling-stroke"/>
      {routes.map((route, index) => <path key={index} className={`brand-pattern-accent brand-pattern-route brand-pattern-route--${index} brand-pattern-tone--${route.tone}${route.strong ? ' brand-pattern-route--strong' : ''}`} d={route.d} strokeWidth={route.strong ? 2.8 : 1.8} strokeLinecap="round" strokeLinejoin="round" vectorEffect="non-scaling-stroke" pathLength="1"/>)}
    </svg>
    <span className="brand-section-symbol">
      <img src={`/brand/icons/${sectionIcons[kind]}-light.svg`} className="brand-section-icon brand-section-icon--light" alt="" width="60" height="60"/>
      <img src={`/brand/icons/${sectionIcons[kind]}-dark.svg`} className="brand-section-icon brand-section-icon--dark" alt="" width="60" height="60"/>
    </span>
  </div>
}
