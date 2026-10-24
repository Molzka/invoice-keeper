type SectionArtKind = 'payments' | 'recurring' | 'history' | 'users' | 'login'

type SectionArtProps = {
  kind: SectionArtKind
  className?: string
}

const ink = '#191e20'
const line = '#b8c1c3'
const paper = '#ffffff'
const plane = '#e9eeef'
const accent = '#c7f0f1'

function InvoiceLines({ x, y, width = 40 }: { x: number; y: number; width?: number }) {
  return <g stroke={line} strokeWidth="1.3">
    <path d={`M${x} ${y}h${width}M${x} ${y + 8}h${width - 10}`} />
    <path d={`M${x} ${y + 25}h${width}M${x} ${y + 33}h${width}M${x} ${y + 41}h${width - 17}`} />
  </g>
}

function Seal({ x, y, radius = 17 }: { x: number; y: number; radius?: number }) {
  return <g className="scene-seal">
    <circle cx={x} cy={y} r={radius} fill={ink} />
    <path d={`M${x - 6} ${y}l4 4 8-9`} stroke="white" strokeWidth="1.8" />
  </g>
}

function PaymentsArt() {
  return <>
    <g className="scene-orbit" stroke={line} strokeWidth="1">
      <path d="M34 132h172M48 140h35M188 140h12" />
      <circle cx="204" cy="40" r="3" />
      <path d="M37 74v8M33 78h8" />
    </g>
    <g className="scene-paper scene-paper--back">
      <g transform="rotate(-12 102 84)">
        <rect x="65" y="30" width="77" height="110" rx="7" fill={plane} stroke={line} strokeWidth="1.2" />
        <path d="M78 46h24M78 53h14" stroke={ink} strokeWidth="1.5" />
        <InvoiceLines x={78} y={73} width={49} />
      </g>
    </g>
    <g className="scene-paper scene-paper--front">
      <path d="M112 30h54l16 16v94l-7-4-7 4-7-4-7 4-7-4-7 4-7-4-7 4-7-4-7 4V30Z" fill={paper} stroke={ink} strokeWidth="1.3" />
      <path d="M166 30v11a5 5 0 0 0 5 5h11" stroke={ink} strokeWidth="1.3" />
      <path d="M125 52h16M125 58h10" stroke={ink} strokeWidth="2" />
      <InvoiceLines x={125} y={74} width={43} />
      <path d="M125 124h23" stroke={ink} strokeWidth="2" />
      <rect x="156" y="121" width="11" height="6" rx="2" fill={accent} />
    </g>
    <Seal x={102} y={119} />
  </>
}

function RecurringArt() {
  return <>
    <g className="scene-orbit" stroke={line} strokeWidth="1.2">
      <path d="M44 82c-6-38 27-61 67-58M109 21l5 3-5 4" />
      <path d="M195 91c7 35-24 59-66 58M132 145l-5 4 5 3" />
      <path d="M34 144h29M177 25h16" />
      <circle cx="204" cy="57" r="3" />
    </g>
    <g className="scene-paper scene-paper--back">
      <g transform="rotate(-8 92 96)">
        <rect x="57" y="48" width="76" height="98" rx="7" fill={plane} stroke={line} strokeWidth="1.2" />
        <rect x="69" y="61" width="13" height="8" rx="2" fill={accent} />
        <InvoiceLines x={69} y={82} width={49} />
        <path d="M69 132h22" stroke={ink} strokeWidth="2" />
      </g>
    </g>
    <g className="scene-paper scene-paper--front">
      <g transform="rotate(6 151 79)">
        <rect x="112" y="28" width="76" height="106" rx="7" fill={paper} stroke={ink} strokeWidth="1.3" />
        <path d="M124 43h20M124 50h11" stroke={ink} strokeWidth="1.8" />
        <InvoiceLines x={124} y={67} width={50} />
        <path d="M124 120h24M164 120h10" stroke={ink} strokeWidth="2" />
      </g>
    </g>
    <g className="scene-seal">
      <circle cx="108" cy="112" r="18" fill={ink} />
      <path d="M101 109a7 7 0 0 1 12-2l2 2m0-5v5h-5M115 115a7 7 0 0 1-12 2l-2-2m0 5v-5h5" stroke="white" strokeWidth="1.3" />
    </g>
  </>
}

function HistoryArt() {
  return <>
    <g className="scene-orbit" stroke={line} strokeWidth="1">
      <path d="M34 140h171M39 37h16M192 44v8M188 48h8" />
      <circle cx="201" cy="118" r="3" />
    </g>
    <g className="scene-paper scene-paper--back">
      <g transform="rotate(-7 128 84)">
        <rect x="80" y="26" width="98" height="113" rx="8" fill={plane} stroke={line} strokeWidth="1.2" />
        <path d="M94 41h37M94 48h22" stroke={line} strokeWidth="1.5" />
      </g>
    </g>
    <g className="scene-paper scene-paper--front">
      <rect x="71" y="45" width="105" height="99" rx="8" fill={paper} stroke={ink} strokeWidth="1.3" />
      <path d="M86 60h27M86 67h15" stroke={ink} strokeWidth="1.7" />
      <path d="M87 87h71M87 108h71M87 129h71" stroke={line} strokeWidth="1" />
      <path d="M99 80h27M99 101h39M99 122h25" stroke={ink} strokeWidth="1.4" />
      <path d="M144 80h14M149 101h9M140 122h18" stroke={line} strokeWidth="1.4" />
      <circle cx="88" cy="80" r="2.5" fill={ink} />
      <circle cx="88" cy="101" r="2.5" fill={ink} />
      <circle cx="88" cy="122" r="3" fill={accent} stroke={line} strokeWidth="1" />
    </g>
    <g className="scene-seal">
      <circle cx="63" cy="64" r="18" fill={ink} />
      <circle cx="63" cy="64" r="9" stroke="white" strokeWidth="1.2" />
      <path d="M63 58v6l4 3" stroke="white" strokeWidth="1.5" />
    </g>
  </>
}

function UsersArt() {
  return <>
    <g className="scene-orbit" stroke={line} strokeWidth="1">
      <path d="M33 140h174M45 43h15M196 85v8M192 89h8" />
      <circle cx="181" cy="28" r="3" />
    </g>
    <g className="scene-paper scene-paper--back">
      <g transform="rotate(-11 94 88)">
        <rect x="53" y="40" width="77" height="103" rx="9" fill={plane} stroke={line} strokeWidth="1.2" />
        <rect x="80" y="49" width="23" height="4" rx="2" fill={line} />
        <circle cx="91.5" cy="77" r="9" stroke={line} strokeWidth="1.3" />
        <path d="M75 103v-4c0-8 7-13 16.5-13S108 91 108 99v4Z" stroke={line} strokeWidth="1.3" />
        <path d="M69 120h43M76 127h29" stroke={line} strokeWidth="1.4" />
      </g>
    </g>
    <g className="scene-paper scene-paper--front">
      <g transform="rotate(6 148 82)">
        <rect x="108" y="25" width="77" height="108" rx="9" fill={paper} stroke={ink} strokeWidth="1.3" />
        <rect x="134" y="35" width="25" height="4" rx="2" fill={ink} />
        <circle cx="146.5" cy="64" r="10" stroke={ink} strokeWidth="1.5" />
        <path d="M128 92v-4c0-9 8-15 18.5-15S165 79 165 88v4Z" fill={plane} stroke={ink} strokeWidth="1.3" />
        <path d="M122 107h49M131 115h31" stroke={line} strokeWidth="1.4" />
        <circle cx="173" cy="48" r="3" fill={accent} />
      </g>
    </g>
    <Seal x={109} y={122} radius={17} />
  </>
}

function LoginArt() {
  return <>
    <g className="scene-orbit" stroke={line} strokeWidth="1">
      <path d="M27 139h187M38 36h18M205 57v8M201 61h8" />
      <path d="M39 107c-9-35 9-67 40-78M184 147c18-6 29-18 32-34" strokeDasharray="3 6" />
      <circle cx="198" cy="29" r="3" />
    </g>
    <g className="scene-paper scene-paper--back">
      <g transform="rotate(-11 107 85)">
        <rect x="61" y="29" width="84" height="114" rx="7" fill={plane} stroke={line} strokeWidth="1.2" />
        <path d="M74 45h25M74 52h14" stroke={ink} strokeWidth="1.6" />
        <InvoiceLines x={74} y={73} width={54} />
      </g>
    </g>
    <g className="scene-paper scene-paper--front">
      <path d="M113 26h47l15 15v83l-6-4-6 4-6-4-6 4-6-4-6 4-6-4-6 4-7-4-7 4V26Z" fill={paper} stroke={ink} strokeWidth="1.3" />
      <path d="M160 26v10a5 5 0 0 0 5 5h10" stroke={ink} strokeWidth="1.3" />
      <path d="M125 49h17M125 56h11" stroke={ink} strokeWidth="1.8" />
      <InvoiceLines x={125} y={73} width={36} />
      <rect x="150" y="105" width="11" height="5" rx="2" fill={accent} />
    </g>
    <g className="scene-seal">
      <rect x="150" y="101" width="53" height="42" rx="8" fill={ink} />
      <path d="M170 119v-4a6.5 6.5 0 0 1 13 0v4" stroke="white" strokeWidth="1.5" />
      <rect x="167" y="119" width="19" height="14" rx="3" stroke="white" strokeWidth="1.5" />
      <path d="M176.5 124v4" stroke="white" strokeWidth="1.5" />
    </g>
  </>
}

const scenes = {
  payments: PaymentsArt,
  recurring: RecurringArt,
  history: HistoryArt,
  users: UsersArt,
  login: LoginArt,
}

/** Small, decorative illustrations that share the same paper-and-ink visual language. */
export function SectionArt({ kind, className }: SectionArtProps) {
  const Scene = scenes[kind]
  return <svg
    className={`section-art section-art--${kind}${className ? ` ${className}` : ''}`}
    viewBox="0 0 240 170"
    fill="none"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
    focusable="false"
  >
    <Scene />
  </svg>
}
