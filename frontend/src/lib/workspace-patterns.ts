import type { WorkspaceArtKind } from '../components/WorkspaceArt'

export type PatternTone = 'cyan' | 'pink'
export interface WorkspaceRoute { d: string; tone: PatternTone; strong?: boolean }
interface WorkspacePattern { routes: WorkspaceRoute[]; guides: string }
const route = (d: string, tone: PatternTone = 'cyan', strong = false): WorkspaceRoute => ({ d, tone, strong })
const pack = (routes: WorkspaceRoute[], guides: string[]): WorkspacePattern => ({ routes, guides: guides.join('') })

/** Separate edge-to-edge compositions; every upper bend remains beyond the copy. */
export function getWorkspacePattern(kind: WorkspaceArtKind, copyEdge: number): WorkspacePattern {
  const base = Math.max(kind === 'payments' ? 740 : 820, copyEdge + (kind === 'receipts' ? 64 : 12))
  const right = Math.max(1720, base + 1000)
  const left = -100, top = -70, bottom = 390

  switch (kind) {
    case 'payments': {
      // The approved horizontal S and its three rising companion lanes.
      const bend = Math.max(740, copyEdge), ret = bend + 300
      return pack([
        route(`M${left} 274H${bend}q54 0 54-54V136q0-54 54-54H${right}`, 'cyan', true),
        route(`M${ret} ${top}V14q0 26 26 26H${right}`, 'pink'),
        route(`M${right} 150H${ret + 100}q-46 0-46 46V${bottom}`),
      ], [0, 1, 2].map(i => `M${left} ${288 + i * 13}H${bend + 134 + i * 22}q26 0 26-26V${136 + i * 14}q0-26 26-26H${right}`))
    }
    case 'recurring':
      // Left entries turn into an upright fan that leaves through the top.
      return pack([
        route(`M${left} 274H${base}q54 0 54-54V${top}`, 'cyan', true),
        route(`M${base + 260} ${top}V14q0 26 26 26H${right}`, 'pink'),
        route(`M${right} 150H${base + 360}q-46 0-46 46V${bottom}`),
      ], [0, 1, 2].map(i => `M${left} ${288 + i * 13}H${base + 94 + i * 22}q26 0 26-26V${top}`))
    case 'calendar': {
      // A two-step rising route instead of a single bend.
      const stair = (dx: number, dy: number) => `M${left} ${274 + dy}H${base + dx}q32 0 32-32V${214 + dy}q0-32 32-32H${base + dx + 184}q32 0 32-32V${112 + dy}q0-32 32-32H${right}`
      return pack([
        route(stair(0, 0), 'cyan', true),
        route(`M${base + 440} ${top}V14q0 26 26 26H${right}`, 'pink'),
        route(`M${right} 178H${base + 560}q-36 0-36 36V${bottom}`),
      ], [1, 2, 3].map(i => stair(i * 44, i * 13)))
    }
    case 'history': {
      // Descending from the top, then flowing out along the lower right.
      const descend = (dx: number, dy: number) => `M${base + dx} ${top}V${74 + dy}q0 54 54 54H${base + dx + 156}q42 0 42 42V${220 + dy}q0 40 40 40H${right}`
      return pack([
        route(descend(0, 0), 'cyan', true),
        route(`M${left} 294H${right}`, 'pink'),
      ], [1, 2, 3].map(i => descend(i * 46, -i * 14)))
    }
    case 'users': {
      // Nested upright arches, a right-hand return and an uninterrupted footline.
      const arch = (inset: number, depth: number, radius: number) => `M${base + inset} ${top}V${depth - radius}q0 ${radius} ${radius} ${radius}H${base + 260 - inset - radius}q${radius} 0 ${radius}-${radius}V${top}`
      return pack([
        route(arch(0, 224, 54), 'cyan', true),
        route(`M${right} 40H${base + 450}q-70 0-70 70V120q0 70 70 70H${right}`, 'pink'),
        route(`M${left} 286H${right}`),
      ], [arch(26, 200, 40), arch(52, 176, 32), arch(78, 152, 24)])
    }
    case 'activity': {
      // A vertical offset spine; companion lanes follow it, rather than the page width.
      const jog = (dx: number, dy: number) => `M${base + dx} ${top}V${64 + dy}q0 42 42 42H${base + dx + 88}q42 0 42 42V${bottom}`
      return pack([
        route(jog(0, 0), 'cyan', true),
        route(`M${left} 282H${base - 130}q32 0 32 32V${bottom}`, 'pink'),
        route(`M${right} 90H${base + 490}q-50 0-50 50V170q0 50 50 50H${right}`),
      ], [1, 2, 3].map(i => jog(i * 46, -i * 14)))
    }
    case 'budget': {
      // Inverted arches rise from the bottom, unlike the top-fed users composition.
      const bridge = (inset: number, height: number, radius: number) => `M${base + inset} ${bottom}V${height + radius}q0-${radius} ${radius}-${radius}H${base + 240 - inset - radius}q${radius} 0 ${radius} ${radius}V${bottom}`
      return pack([
        route(bridge(0, 70, 54), 'cyan', true),
        route(`M${left} 280H${base - 100}q32 0 32 32V${bottom}`, 'pink'),
        route(`M${base + 370} ${top}V20q0 36 36 36H${right}`),
      ], [bridge(28, 94, 38), bridge(56, 118, 30), bridge(84, 142, 22)])
    }
    case 'receipts': {
      // A broad C-shaped return with both ends at the right edge.
      const fold = (inset: number, upper: number, lower: number, radius: number) => `M${right} ${upper}H${base + inset + radius}q-${radius} 0-${radius} ${radius}V${lower - radius}q0 ${radius} ${radius} ${radius}H${right}`
      return pack([
        route(fold(16, 46, 234, 54), 'cyan', true),
        route(`M${left} 286H${base - 100}q54 0 54-54V${top}`, 'pink'),
        route(`M${left} 314H${right}`),
      ], [fold(70, 72, 208, 40), fold(122, 98, 182, 28), fold(174, 124, 156, 16)])
    }
  }
}
