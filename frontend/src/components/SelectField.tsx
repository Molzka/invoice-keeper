import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import type { KeyboardEvent } from 'react'
import { createPortal } from 'react-dom'
import { Check, ChevronDown } from './BrandIcons'

export interface SelectOption {
  value: string
  label: string
  description?: string
}

export interface SelectFieldProps {
  value: string
  onChange: (value: string) => void
  options: SelectOption[]
  id?: string
  name?: string
  disabled?: boolean
  required?: boolean
  className?: string
  'aria-label'?: string
  'aria-invalid'?: boolean
  'aria-describedby'?: string
}

/** Keeps keyboard focus on its trigger so it also works inside a focus-trapped drawer. */
export function SelectField({ value, onChange, options, id, name, disabled, required, className, 'aria-label': ariaLabel, 'aria-invalid': ariaInvalid, 'aria-describedby': ariaDescribedBy }: SelectFieldProps) {
  const generatedId = useId()
  const triggerId = id ?? `ik-select-${generatedId}`
  const menuId = `${triggerId}-options`
  const triggerRef = useRef<HTMLButtonElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const search = useRef({ text: '', time: 0 })
  const selectedIndex = options.findIndex(option => option.value === value)
  const [open, setOpen] = useState(false)
  const [present, setPresent] = useState(false)
  const [activeIndex, setActiveIndex] = useState(Math.max(0, selectedIndex))

  const closeMenu = useCallback((restoreFocus = false) => {
    setOpen(false)
    search.current = { text: '', time: 0 }
    if (restoreFocus) triggerRef.current?.focus({ preventScroll: true })
    if (closeTimer.current) clearTimeout(closeTimer.current)
    closeTimer.current = setTimeout(() => setPresent(false), 140)
  }, [])

  function openMenu(index = Math.max(0, selectedIndex)) {
    if (disabled || options.length === 0) return
    if (closeTimer.current) clearTimeout(closeTimer.current)
    search.current = { text: '', time: 0 }
    setActiveIndex(Math.min(options.length - 1, Math.max(0, index)))
    setPresent(true)
    setOpen(true)
  }

  function choose(index: number) {
    const option = options[index]
    if (!option) return
    onChange(option.value)
    closeMenu(true)
  }

  useEffect(() => () => { if (closeTimer.current) clearTimeout(closeTimer.current) }, [])

  useLayoutEffect(() => {
    if (!present) return
    const positionMenu = () => {
      const trigger = triggerRef.current
      const menu = menuRef.current
      if (!trigger || !menu) return
      const rect = trigger.getBoundingClientRect()
      const viewportWidth = document.documentElement.clientWidth
      const viewportHeight = window.visualViewport?.height ?? window.innerHeight
      const viewportTop = window.visualViewport?.offsetTop ?? 0
      const edge = 8
      const gap = 8
      const width = Math.min(Math.max(rect.width, className?.includes('ik-select-compact') ? rect.width : 220), viewportWidth - edge * 2)
      const below = viewportTop + viewportHeight - rect.bottom - gap - edge
      const above = rect.top - viewportTop - gap - edge
      const estimatedHeight = Math.min(menu.scrollHeight, 312)
      const placeBelow = below >= estimatedHeight || below >= above
      const maxHeight = Math.max(40, Math.min(312, placeBelow ? below : above))
      menu.style.width = `${width}px`
      menu.style.maxHeight = `${maxHeight}px`
      menu.style.left = `${Math.max(edge, Math.min(rect.left, viewportWidth - width - edge))}px`
      const height = menu.offsetHeight
      menu.style.top = `${Math.max(viewportTop + edge, placeBelow ? rect.bottom + gap : rect.top - height - gap)}px`
      menu.dataset.side = placeBelow ? 'bottom' : 'top'
    }
    positionMenu()
    const onOutside = (event: PointerEvent) => {
      if (!(event.target instanceof Node)) return
      if (!triggerRef.current?.contains(event.target) && !menuRef.current?.contains(event.target)) closeMenu()
    }
    document.addEventListener('pointerdown', onOutside, true)
    window.addEventListener('resize', positionMenu)
    window.addEventListener('scroll', positionMenu, true)
    window.visualViewport?.addEventListener('resize', positionMenu)
    window.visualViewport?.addEventListener('scroll', positionMenu)
    return () => {
      document.removeEventListener('pointerdown', onOutside, true)
      window.removeEventListener('resize', positionMenu)
      window.removeEventListener('scroll', positionMenu, true)
      window.visualViewport?.removeEventListener('resize', positionMenu)
      window.visualViewport?.removeEventListener('scroll', positionMenu)
    }
  }, [present, options, closeMenu, className])

  useLayoutEffect(() => {
    if (!open) return
    const menu = menuRef.current
    const option = menu?.querySelector<HTMLElement>('[data-active="true"]')
    if (!menu || !option) return
    const top = option.offsetTop
    if (top < menu.scrollTop) menu.scrollTop = top
    else if (top + option.offsetHeight > menu.scrollTop + menu.clientHeight) menu.scrollTop = top + option.offsetHeight - menu.clientHeight
  }, [activeIndex, open])

  function onKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    if (disabled || options.length === 0) return
    if (event.key === 'Escape' && open) {
      event.preventDefault()
      event.stopPropagation()
      closeMenu(true)
      return
    }
    if (event.key === 'Tab') { if (open) closeMenu(true); return }
    if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
      event.preventDefault()
      if (event.key === 'Home') { if (!open) openMenu(0); else setActiveIndex(0) }
      else if (event.key === 'End') { if (!open) openMenu(options.length - 1); else setActiveIndex(options.length - 1) }
      else if (!open) openMenu(selectedIndex >= 0 ? selectedIndex : event.key === 'ArrowUp' ? options.length - 1 : 0)
      else setActiveIndex(index => (index + (event.key === 'ArrowDown' ? 1 : -1) + options.length) % options.length)
      return
    }
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      if (open) choose(activeIndex)
      else openMenu()
      return
    }
    if (event.key.length !== 1 || event.altKey || event.ctrlKey || event.metaKey) return
    event.preventDefault()
    const now = performance.now()
    const character = event.key.toLocaleLowerCase('ru')
    const previous = now - search.current.time < 650 ? search.current.text : ''
    const text = previous + character
    const repeated = [...text].every(letter => letter === character)
    const prefix = repeated ? character : text
    const start = open ? activeIndex : selectedIndex
    const firstOffset = repeated ? 1 : 0
    const match = Array.from({ length: options.length }, (_, offset) => (Math.max(0, start) + offset + firstOffset) % options.length)
      .find(index => options[index].label.toLocaleLowerCase('ru').startsWith(prefix))
    if (!open) openMenu(match ?? Math.max(0, selectedIndex))
    else if (match !== undefined) setActiveIndex(match)
    search.current = { text, time: now }
  }

  return <div className={`ik-select${className ? ` ${className}` : ''}`}>
    <button ref={triggerRef} id={triggerId} type="button" role="combobox" className="ik-field-trigger ik-select-trigger"
      aria-label={ariaLabel} aria-expanded={open} aria-controls={menuId} aria-haspopup="listbox"
      aria-activedescendant={open && options[activeIndex] ? `${menuId}-${activeIndex}` : undefined}
      aria-required={required || undefined} aria-invalid={ariaInvalid} aria-describedby={ariaDescribedBy}
      disabled={disabled} data-open={open} onKeyDown={onKeyDown}
      onBlur={() => { if (open) closeMenu() }} onClick={() => { if (open) closeMenu(); else openMenu() }}>
      <span className="ik-select-value">{options[selectedIndex]?.label ?? 'Выберите значение'}</span>
      <ChevronDown size={17} aria-hidden="true" className="ik-select-chevron"/>
    </button>
    {(name || required) && <select className="ik-select-native" aria-hidden="true" tabIndex={-1} name={name} value={value}
      disabled={disabled} required={required} onChange={event => onChange(event.target.value)}
      onInvalid={event => { event.preventDefault(); triggerRef.current?.focus(); openMenu() }}>
      {!options.some(option => option.value === '') && <option value=""/>}
      {options.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
    </select>}
    {present && createPortal(<div ref={menuRef} id={menuId} role="listbox" aria-label={ariaLabel} aria-labelledby={ariaLabel ? undefined : triggerId}
      className="ik-field-popover ik-select-menu" data-field-popover data-state={open ? 'open' : 'closed'} aria-hidden={!open || undefined}>
      {options.map((option, index) => <div key={option.value} id={`${menuId}-${index}`} role="option"
        aria-selected={option.value === value} data-active={index === activeIndex} className="ik-select-option"
        onPointerMove={event => { if (event.pointerType !== 'touch') setActiveIndex(index) }}
        onPointerDown={event => event.preventDefault()} onClick={() => choose(index)}>
        <span className="ik-select-option-copy"><span>{option.label}</span>{option.description && <small>{option.description}</small>}</span>
        {option.value === value && <Check size={16} aria-hidden="true" className="ik-select-check"/>}
      </div>)}
    </div>, triggerRef.current?.closest('[role="dialog"][aria-modal="true"]')?.querySelector('[data-drawer-popover-root]') ?? document.body)}
  </div>
}
