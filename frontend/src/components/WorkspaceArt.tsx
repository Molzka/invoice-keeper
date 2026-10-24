import { useId } from 'react'

export type WorkspaceArtKind = 'payments' | 'recurring' | 'history' | 'users' | 'calendar' | 'activity'

interface WorkspaceArtProps {
  kind: WorkspaceArtKind
  className?: string
}

interface ScenePaint {
  paper: string
  back: string
  badge: string
  halo: string
}

const routes: Record<WorkspaceArtKind, string> = {
  calendar: 'M12 112H96C126 112 129 58 160 58H227C260 58 260 120 295 120H356C381 120 379 83 397 83',
  activity: 'M12 112H93C126 112 125 59 157 59H229C260 59 264 119 299 119H357C381 119 379 83 397 83',
  payments: 'M12 116H102C128 116 128 67 160 67H228C266 67 258 125 298 125H354C379 125 376 86 397 86',
  recurring: 'M12 107H77C113 107 108 49 145 49H227C266 49 261 118 298 118H358C380 118 381 89 397 89',
  history: 'M12 120H91C128 120 121 77 156 77H226C260 77 258 111 294 111H360C381 111 380 84 397 84',
  users: 'M12 112H89C121 112 124 55 155 55H227C260 55 264 119 299 119H354C378 119 377 83 397 83',
}

function DocumentLines({ x, y, width = 38 }: { x: number; y: number; width?: number }) {
  return <g className="workspace-art-detail">
    <path d={`M${x} ${y}h${width}M${x} ${y + 8}h${width - 12}`} />
    <path d={`M${x} ${y + 25}h${width}M${x} ${y + 33}h${width - 6}`} />
  </g>
}

function SceneBadge({ x, y, paint, kind = 'check' }: { x: number; y: number; paint: ScenePaint; kind?: 'check' | 'cycle' | 'clock' }) {
  return <g className="workspace-art-badge">
    <circle cx={x + 1} cy={y + 3} r="17" className="workspace-art-badge-shadow" stroke="none" />
    <circle cx={x} cy={y} r="17" fill={paint.badge} stroke="white" strokeWidth="3" />
    <path d={`M${x - 10} ${y - 7}a12 12 0 0 1 15-4`} stroke="white" strokeOpacity=".3" strokeWidth="1.2" />
    <g stroke="white" strokeWidth="1.8">
      {kind === 'check' && <path d={`m${x - 6} ${y} 4 4 8-9`} />}
      {kind === 'clock' && <><circle cx={x} cy={y} r="8" strokeWidth="1.3"/><path d={`M${x} ${y - 5}v5l4 3`} /></>}
      {kind === 'cycle' && <><path d={`M${x - 7} ${y - 2}a7 7 0 0 1 12-2l2 2m0-5v5h-5M${x + 7} ${y + 3}a7 7 0 0 1-12 2l-2-2m0 5v-5h5`} strokeWidth="1.4" /></>}
    </g>
  </g>
}

function PaymentsScene({ paint }: { paint: ScenePaint }) {
  return <>
    <g className="workspace-art-secondary" transform="rotate(-9 435 91)">
      <rect x="400" y="39" width="69" height="103" rx="7" fill={paint.back} />
      <path d="M411 53h21M411 61h12" className="workspace-art-heading" />
      <DocumentLines x={411} y={78} width={45} />
      <path d="M410 131h47" strokeOpacity=".4" />
    </g>
    <path className="workspace-art-paper" fill={paint.paper} d="M425 28h48l14 14v99l-6-4-6 4-6-4-6 4-6-4-6 4-6-4-6 4-7-4-7 4V28Z" />
    <path d="M473 28v10a4 4 0 0 0 4 4h10Z" className="workspace-art-fold" />
    <path d="M437 50h17M437 57h11" className="workspace-art-heading" />
    <DocumentLines x={437} y={75} width={37} />
    <path d="M437 124h18" className="workspace-art-heading" />
    <rect x="460" y="120" width="13" height="7" rx="3" className="workspace-art-chip" stroke="none" />
    <SceneBadge x={491} y={124} paint={paint}/>
  </>
}

function RecurringScene({ paint }: { paint: ScenePaint }) {
  return <>
    <g className="workspace-art-secondary" transform="rotate(-7 425 96)">
      <rect x="398" y="54" width="62" height="90" rx="7" fill={paint.back} />
      <rect x="410" y="66" width="18" height="7" rx="3" className="workspace-art-chip" stroke="none" />
      <DocumentLines x={410} y={82} width={36} />
    </g>
    <g transform="rotate(5 468 78)">
      <rect className="workspace-art-paper" fill={paint.paper} x="436" y="31" width="62" height="92" rx="7" />
      <path d="M447 45h18M447 52h10" className="workspace-art-heading" />
      <DocumentLines x={447} y={68} width={37} />
      <path d="M447 111h20" className="workspace-art-heading" />
    </g>
    <path className="workspace-art-cycle" d="M408 39c17-22 52-24 77-7m-1-8 1 8-8 1M490 150c-22 15-48 14-67 2m1 8-1-8 8-1" />
    <SceneBadge x={491} y={123} paint={paint} kind="cycle"/>
  </>
}

function HistoryScene({ paint }: { paint: ScenePaint }) {
  return <>
    <g className="workspace-art-secondary">
      <rect x="421" y="32" width="73" height="100" rx="7" fill={paint.back} transform="rotate(6 458 83)" />
      <rect x="415" y="39" width="73" height="100" rx="7" fill={paint.back} />
    </g>
    <rect className="workspace-art-paper" fill={paint.paper} x="408" y="46" width="75" height="95" rx="7" />
    <rect x="408" y="46" width="75" height="27" rx="7" className="workspace-art-topline" stroke="none" />
    <path d="M421 58h24M421 65h14" className="workspace-art-heading" />
    <path d="M422 84v38" className="workspace-art-cycle" />
    <circle className="workspace-art-point" cx="422" cy="85" r="3" />
    <circle className="workspace-art-point" cx="422" cy="103" r="3" />
    <circle className="workspace-art-point" cx="422" cy="121" r="3" />
    <path className="workspace-art-detail" d="M432 85h35M432 103h27M432 121h31" />
    <SceneBadge x={490} y={126} paint={paint} kind="clock"/>
  </>
}

function UsersScene({ paint }: { paint: ScenePaint }) {
  return <>
    <g className="workspace-art-secondary" transform="rotate(-9 425 97)">
      <rect x="397" y="50" width="59" height="94" rx="8" fill={paint.back} />
      <path d="M417 59h19" className="workspace-art-heading" />
      <circle cx="427" cy="83" r="8" className="workspace-art-portrait" />
      <path d="M414 106v-4c0-7 5-11 13-11s13 4 13 11v4Z" className="workspace-art-portrait" />
      <path d="M409 122h35M416 129h21" className="workspace-art-detail" />
    </g>
    <g transform="rotate(5 468 81)">
      <rect className="workspace-art-paper" fill={paint.paper} x="437" y="31" width="60" height="98" rx="8" />
      <rect x="458" y="39" width="18" height="4" rx="2" className="workspace-art-chip" stroke="none" />
      <circle cx="467" cy="64" r="9" className="workspace-art-portrait" />
      <path d="M452 89v-5c0-7 6-12 15-12s15 5 15 12v5Z" className="workspace-art-portrait" />
      <path className="workspace-art-detail" d="M449 105h36M456 113h22" />
    </g>
    <SceneBadge x={493} y={125} paint={paint}/>
  </>
}

function CalendarScene({ paint }: { paint: ScenePaint }) {
  return <>
    <g className="workspace-art-secondary" transform="rotate(-8 450 91)"><rect x="408" y="39" width="81" height="102" rx="9" fill={paint.back}/></g>
    <rect className="workspace-art-paper" x="419" y="33" width="81" height="108" rx="9" fill={paint.paper}/>
    <path className="workspace-art-topline" d="M428 33h63a9 9 0 0 1 9 9v17h-81V42a9 9 0 0 1 9-9Z" stroke="none"/>
    <path className="workspace-art-heading" d="M436 26v15m47-15v15M432 50h20"/>
    <g className="workspace-art-detail"><path d="M433 76h4m16 0h4m16 0h4M433 96h4m16 0h4m16 0h4M433 116h4m16 0h4m16 0h4"/></g>
    <rect x="447" y="87" width="17" height="17" rx="5" className="workspace-art-chip" stroke="none"/>
    <path d="m451 95 3 3 6-7" stroke="white" strokeWidth="1.6"/>
    <SceneBadge x={496} y={132} paint={paint} kind="clock"/>
  </>
}

function ActivityScene({ paint }: { paint: ScenePaint }) {
  return <>
    <g className="workspace-art-secondary" transform="rotate(7 454 91)"><rect x="416" y="37" width="78" height="108" rx="8" fill={paint.back}/></g>
    <rect className="workspace-art-paper" x="410" y="33" width="78" height="107" rx="8" fill={paint.paper}/>
    <path className="workspace-art-heading" d="M424 48h24M424 55h14"/>
    <path className="workspace-art-cycle" d="M426 75v48"/>
    {[76,97,118].map((y,i) => <g key={y}><circle cx="426" cy={y} r="4" className="workspace-art-point"/><path d={`M437 ${y-2}h${i===1?25:33}M437 ${y+5}h19`} className="workspace-art-detail"/></g>)}
    <SceneBadge x={492} y={125} paint={paint}/>
  </>
}

const scenes = {
  calendar: CalendarScene,
  activity: ActivityScene,
  payments: PaymentsScene,
  recurring: RecurringScene,
  history: HistoryScene,
  users: UsersScene,
}

/** Colorful paper scenes stay within the header's free column, away from its controls. */
export function WorkspaceArt({ kind, className }: WorkspaceArtProps) {
  const id = `workspace-${useId().replace(/[^a-zA-Z0-9_-]/g, '')}`
  const maskId = `${id}-route`
  const route = routes[kind]
  const Scene = scenes[kind]
  const paint: ScenePaint = { paper: `url(#${id}-paper)`, back: `url(#${id}-back)`, badge: `url(#${id}-badge)`, halo: `url(#${id}-halo)` }

  return <svg
    className={`workspace-art workspace-art--${kind}${className ? ` ${className}` : ''}`}
    viewBox="0 0 560 180"
    preserveAspectRatio="xMaxYMid slice"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.2"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
    focusable="false"
  >
    <defs>
      <linearGradient id={`${id}-paper`} x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" stopColor="#ffffff"/><stop offset=".48" stopColor="#ffffff"/><stop offset="1" stopColor="var(--art-paper-end)"/>
      </linearGradient>
      <linearGradient id={`${id}-back`} x1="0" y1="0" x2="1" y2="1">
        <stop stopColor="var(--art-wash)"/><stop offset="1" stopColor="var(--art-tint)"/>
      </linearGradient>
      <linearGradient id={`${id}-badge`} x1="0" y1="0" x2="1" y2="1">
        <stop stopColor="var(--art-accent)"/><stop offset="1" stopColor="var(--art-accent-deep)"/>
      </linearGradient>
      <radialGradient id={`${id}-halo`}>
        <stop stopColor="var(--art-tint)" stopOpacity=".65"/><stop offset="1" stopColor="var(--art-tint)" stopOpacity="0"/>
      </radialGradient>
      <mask id={maskId} x="0" y="0" width="560" height="180" maskUnits="userSpaceOnUse">
        <path className="workspace-art-reveal" d={route} pathLength="1" stroke="white" strokeWidth="10" strokeDasharray="1" />
      </mask>
    </defs>
    <g className="workspace-art-route">
      <path d={route} strokeDasharray="2 7" mask={`url(#${maskId})`} />
      <path className="workspace-art-arrow" d={kind === 'payments' ? 'm391 81 6 5-6 5' : kind === 'recurring' ? 'm391 84 6 5-6 5' : kind === 'history' ? 'm391 79 6 5-6 5' : 'm391 78 6 5-6 5'} />
      <circle cx="12" cy={kind === 'payments' ? '116' : kind === 'recurring' ? '107' : kind === 'history' ? '120' : '112'} r="3" />
      <circle cx="274" cy="45" r="2" className="workspace-art-node" />
      <path className="workspace-art-node" d="M328 72h7m-3.5-3.5v7M175 143h17" />
    </g>
    <g className="workspace-art-object">
      <ellipse cx="452" cy="92" rx="88" ry="78" fill={paint.halo} stroke="none"/>
      <ellipse cx="450" cy="151" rx="59" ry="6" className="workspace-art-ground" stroke="none"/>
      <path className="workspace-art-spark" d="M517 52v10M512 57h10M389 115v6M386 118h6"/>
      <circle cx="516" cy="100" r="3" className="workspace-art-point"/>
      <circle cx="398" cy="30" r="2" className="workspace-art-point"/>
      <Scene paint={paint}/>
    </g>
  </svg>
}
