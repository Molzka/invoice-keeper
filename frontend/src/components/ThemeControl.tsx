import { useEffect, useId, useRef } from 'react'
import { Monitor, Moon, Sun } from './BrandIcons'
import { useTheme } from '../lib/useTheme'
import type { ThemePreference } from '../lib/theme'
const choices: { value: ThemePreference; label: string; icon: typeof Sun }[] = [
  { value: 'light', label: 'Светлая', icon: Sun },
  { value: 'dark', label: 'Тёмная', icon: Moon },
  { value: 'system', label: 'Как в системе', icon: Monitor },
]
export function ThemeControl() {
  const { preference, resolved, setPreference } = useTheme()
  const details = useRef<HTMLDetailsElement>(null)
  const id = useId()
  const Icon = resolved === 'dark' ? Moon : Sun
  function positionMenu() {
    const element = details.current
    const menu = element?.querySelector<HTMLElement>('.theme-options')
    const trigger = element?.querySelector('summary')
    if (!element?.open || !menu || !trigger) return
    const bounds = element.getBoundingClientRect()
    const triggerBounds = trigger.getBoundingClientRect()
    const width = menu.getBoundingClientRect().width
    const left = Math.min(Math.max(16, triggerBounds.right - width), window.innerWidth - width - 16)
    menu.style.left = (left - bounds.left) + 'px'
    menu.style.right = 'auto'
  }
  useEffect(() => {
    function closeOutside(event: Event) { if (event.target instanceof Node && !details.current?.contains(event.target) && details.current) details.current.open = false }
    function escape(event: KeyboardEvent) {
      if (event.key === 'Escape' && details.current?.open) { event.preventDefault(); details.current.open = false; details.current.querySelector('summary')?.focus() }
    }
    document.addEventListener('pointerdown', closeOutside)
    document.addEventListener('focusin', closeOutside)
    window.addEventListener('resize', positionMenu)
    document.addEventListener('keydown', escape)
    return () => { document.removeEventListener('pointerdown', closeOutside); document.removeEventListener('focusin', closeOutside); window.removeEventListener('resize', positionMenu); document.removeEventListener('keydown', escape) }
  }, [])
  return <details ref={details} className="theme-control" onToggle={positionMenu}><summary className="icon-button theme-toggle" aria-label="Тема оформления" title="Тема оформления"><Icon size={19}/></summary><fieldset className="theme-options"><legend>Тема интерфейса</legend>{choices.map(({ value, label, icon: ChoiceIcon }) => <label className="theme-option" key={value}><input type="radio" name={`theme-${id}`} checked={preference === value} value={value} onChange={() => { setPreference(value); if (details.current) { details.current.open = false; details.current.querySelector('summary')?.focus() } }}/><ChoiceIcon size={17}/><span>{label}</span></label>)}</fieldset></details>
}
