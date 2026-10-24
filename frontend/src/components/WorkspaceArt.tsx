import { useId } from 'react'

export type WorkspaceArtKind = 'payments' | 'recurring' | 'history' | 'users'

interface WorkspaceArtProps {
  kind: WorkspaceArtKind
  className?: string
}

const routes: Record<WorkspaceArtKind, string> = {
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

function PaymentsOutline() {
  return <>
    <g className="workspace-art-secondary" transform="rotate(-9 435 91)">
      <rect x="400" y="39" width="69" height="103" rx="5" />
      <path d="M411 53h21M411 61h12" />
      <DocumentLines x={411} y={78} width={45} />
    </g>
    <path className="workspace-art-paper" d="M425 28h48l14 14v99l-6-4-6 4-6-4-6 4-6-4-6 4-6-4-6 4-7-4-7 4V28Z" />
    <path d="M473 28v10a4 4 0 0 0 4 4h10M437 50h17M437 57h11" />
    <DocumentLines x={437} y={75} width={37} />
    <path d="M437 124h18" />
    <circle cx="490" cy="121" r="14" className="workspace-art-paper" />
    <path d="m484 121 4 4 8-9" />
  </>
}

function RecurringOutline() {
  return <>
    <g className="workspace-art-secondary" transform="rotate(-7 425 96)">
      <rect x="398" y="54" width="62" height="90" rx="5" />
      <path d="M410 68h20" />
      <DocumentLines x={410} y={82} width={36} />
    </g>
    <g transform="rotate(5 468 78)">
      <rect className="workspace-art-paper" x="436" y="31" width="62" height="92" rx="5" />
      <path d="M447 45h18M447 52h10" />
      <DocumentLines x={447} y={68} width={37} />
    </g>
    <path d="M408 39c17-22 52-24 77-7m-1-8 1 8-8 1M490 143c-22 15-48 14-67 2m1 8-1-8 8-1" />
  </>
}

function HistoryOutline() {
  return <>
    <path className="workspace-art-secondary" d="M422 33h68a5 5 0 0 1 5 5v91M416 39h68a5 5 0 0 1 5 5v91" />
    <rect className="workspace-art-paper" x="409" y="46" width="75" height="95" rx="5" />
    <path d="M422 61h24M422 68h14M423 84v38" />
    <circle className="workspace-art-paper" cx="423" cy="85" r="3" />
    <circle className="workspace-art-paper" cx="423" cy="103" r="3" />
    <circle className="workspace-art-paper" cx="423" cy="121" r="3" />
    <path className="workspace-art-detail" d="M433 85h35M433 103h27M433 121h31" />
    <circle cx="492" cy="127" r="13" className="workspace-art-paper" />
    <path d="M492 120v7l4 3" />
  </>
}

function UsersOutline() {
  return <>
    <g className="workspace-art-secondary" transform="rotate(-9 425 97)">
      <rect x="397" y="50" width="59" height="94" rx="7" />
      <path d="M417 59h19" />
      <circle cx="427" cy="83" r="8" />
      <path d="M414 106v-4c0-7 5-11 13-11s13 4 13 11v4ZM409 122h35M416 129h21" />
    </g>
    <g transform="rotate(5 468 81)">
      <rect className="workspace-art-paper" x="437" y="31" width="60" height="98" rx="7" />
      <path d="M458 40h18" />
      <circle cx="467" cy="64" r="9" />
      <path d="M452 89v-5c0-7 6-12 15-12s15 5 15 12v5Z" />
      <path className="workspace-art-detail" d="M449 105h36M456 113h22" />
    </g>
    <circle cx="493" cy="126" r="12" className="workspace-art-paper" />
    <path d="m488 126 3 3 6-7" />
  </>
}

const outlines = {
  payments: PaymentsOutline,
  recurring: RecurringOutline,
  history: HistoryOutline,
  users: UsersOutline,
}

/** Decorative ink routes stay within the header's free column, away from its controls. */
export function WorkspaceArt({ kind, className }: WorkspaceArtProps) {
  const maskId = `workspace-route-${useId().replace(/:/g, '')}`
  const route = routes[kind]
  const Outline = outlines[kind]

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
      <Outline />
    </g>
  </svg>
}
