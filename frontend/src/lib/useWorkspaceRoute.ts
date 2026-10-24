import { useMemo, useSyncExternalStore } from 'react'
import { readPaymentRoute } from './payment-route'

const routeEvent = 'invoice:routechange'
function subscribe(onChange: () => void) {
  window.addEventListener('hashchange', onChange)
  window.addEventListener('popstate', onChange)
  window.addEventListener(routeEvent, onChange)
  return () => {
    window.removeEventListener('hashchange', onChange)
    window.removeEventListener('popstate', onChange)
    window.removeEventListener(routeEvent, onChange)
  }
}
function snapshot() { return window.location.hash }

export function useWorkspaceRoute(today: string | null) {
  const hash = useSyncExternalStore(subscribe, snapshot)
  return useMemo(() => today ? readPaymentRoute(hash, today) : null, [hash, today])
}

export function writeWorkspaceHash(hash: string, replace = false) {
  if (window.location.hash === hash) return
  if (replace) {
    window.history.replaceState(window.history.state, '', hash)
    window.dispatchEvent(new Event(routeEvent))
  } else window.location.hash = hash
}
