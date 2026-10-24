import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import type { KeyboardEvent } from 'react'
import { createPortal } from 'react-dom'
import { CalendarDays, ChevronDown, ChevronLeft, ChevronRight, X } from './BrandIcons'
import { calendarMonthDate } from '../config/demo'

type Props = {
  id: string; name?: string; value: string; onChange: (value: string) => void; today: string
  min?: string; max?: string; disabled?: boolean; required?: boolean
  'aria-label'?: string; 'aria-invalid'?: boolean; 'aria-describedby'?: string
}
type CalendarView = 'days' | 'months' | 'years'
const months = ['Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь', 'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь']
const dayNames = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']
const longDate = new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC' })
function dateObject(value: string) { return new Date(value + 'T12:00:00Z') }
function displayDate(value: string) { return value ? value.split('-').reverse().join('.') : 'дд.мм.гггг' }
function moveDays(value: string, offset: number) {
  const date = dateObject(value)
  date.setUTCDate(date.getUTCDate() + offset)
  const year = date.getUTCFullYear()
  if (year < 1 || year > 9999) return ''
  return String(year).padStart(4, '0') + '-' + String(date.getUTCMonth() + 1).padStart(2, '0') + '-' + String(date.getUTCDate()).padStart(2, '0')
}

export function DatePicker({ id, name, value, onChange, today, min = '0001-01-01', max = '9999-12-31', disabled, required, ...aria }: Props) {
  const popupId = useId()
  const monthId = useId()
  const trigger = useRef<HTMLButtonElement>(null)
  const popup = useRef<HTMLDivElement>(null)
  const focusRequested = useRef(false)
  const viewFocusRequested = useRef(false)
  const [open, setOpen] = useState(false)
  const [mounted, setMounted] = useState(false)
  const [view, setView] = useState<CalendarView>('days')
  const [month, setMonth] = useState((value || today).slice(0, 7))
  const [active, setActive] = useState(value || today)
  const [yearStart, setYearStart] = useState(Math.max(1, Number((value || today).slice(0, 4)) - 5))
  const [position, setPosition] = useState({ top: 0, left: 0, width: 304, maxHeight: 440 })
  const expanded = open && !disabled
  const inRange = (date: string) => Boolean(date) && date >= min && date <= max
  const clamp = (date: string) => date < min ? min : date > max ? max : date
  const [year, monthNumber] = month.split('-').map(Number)
  const first = month + '-01'
  const weekdayOffset = (dateObject(first).getUTCDay() + 6) % 7
  const days = Array.from({ length: 42 }, (_, index) => moveDays(first, index - weekdayOffset))

  const positionPopup = useCallback(() => {
    if (!trigger.current || !popup.current) return
    const anchor = trigger.current.getBoundingClientRect()
    const viewportWidth = document.documentElement.clientWidth
    const viewportHeight = window.visualViewport?.height ?? window.innerHeight
    const width = Math.min(304, viewportWidth - 24)
    const height = Math.min(popup.current.offsetHeight, viewportHeight - 24)
    const below = anchor.bottom + 8
    const top = below + height <= viewportHeight - 12 ? below : Math.max(12, anchor.top - height - 8)
    const left = Math.max(12, Math.min(anchor.left, viewportWidth - width - 12))
    setPosition({ top, left, width, maxHeight: viewportHeight - 24 })
  }, [])

  useLayoutEffect(() => {
    if (!expanded) return
    positionPopup()
    const observer = new ResizeObserver(positionPopup)
    if (popup.current) observer.observe(popup.current)
    window.addEventListener('resize', positionPopup)
    window.addEventListener('scroll', positionPopup, true)
    window.visualViewport?.addEventListener('resize', positionPopup)
    return () => {
      observer.disconnect()
      window.removeEventListener('resize', positionPopup)
      window.removeEventListener('scroll', positionPopup, true)
      window.visualViewport?.removeEventListener('resize', positionPopup)
    }
  }, [expanded, view, positionPopup])

  useLayoutEffect(() => {
    if (expanded && view === 'days' && focusRequested.current) {
      popup.current?.querySelector<HTMLButtonElement>('[data-date="' + active + '"]')?.focus({ preventScroll: true })
      focusRequested.current = false
    }
  }, [expanded, view, active, month])

  useLayoutEffect(() => {
    if (expanded && view !== 'days' && viewFocusRequested.current) {
      const target = popup.current?.querySelector<HTMLButtonElement>('.ik-calendar-picks button[data-selected="true"]:not(:disabled)') ?? popup.current?.querySelector<HTMLButtonElement>('.ik-calendar-picks button:not(:disabled)')
      target?.focus({ preventScroll: true })
      viewFocusRequested.current = false
    }
  }, [expanded, view, yearStart, month])

  useEffect(() => {
    if (!expanded) return
    const outside = (event: PointerEvent) => {
      const target = event.target as Node
      if (!trigger.current?.contains(target) && !popup.current?.contains(target)) setOpen(false)
    }
    document.addEventListener('pointerdown', outside, true)
    return () => document.removeEventListener('pointerdown', outside, true)
  }, [expanded])

  function close(restoreFocus = true) {
    setOpen(false)
    if (restoreFocus) trigger.current?.focus({ preventScroll: true })
  }
  function show() {
    if (disabled) return
    if (expanded) { close(); return }
    const reference = clamp(value || today)
    setMonth(reference.slice(0, 7)); setActive(reference); setView('days')
    setYearStart(Math.min(9988, Math.max(1, Number(reference.slice(0, 4)) - 5)))
    focusRequested.current = true
    setMounted(true); setOpen(true)
  }
  function choose(date: string) { if (inRange(date)) { onChange(date); close() } }
  function changeMonth(next: string, focus = false) {
    const nextDate = clamp(calendarMonthDate(next, Number(active.slice(8, 10))))
    setMonth(nextDate.slice(0, 7)); setActive(nextDate); setView('days')
    focusRequested.current = focus
  }
  function canNavigate(offset: number) {
    const target = calendarMonthDate(first, 1, offset)
    return /^\d{4}-\d{2}-\d{2}$/.test(target) && target.slice(0, 7) >= min.slice(0, 7) && target.slice(0, 7) <= max.slice(0, 7)
  }
  function showView(next: CalendarView) {
    if (next === 'days') focusRequested.current = true
    else viewFocusRequested.current = true
    setView(next)
  }
  function popupKey(event: KeyboardEvent) {
    if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close() }
    if (event.key === 'Tab') {
      event.stopPropagation()
      const buttons = Array.from(popup.current?.querySelectorAll<HTMLButtonElement>('button:not(:disabled):not([tabindex="-1"])') ?? [])
      const first = buttons[0], last = buttons.at(-1)
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
    }
  }
  function dayKey(event: KeyboardEvent<HTMLButtonElement>, date: string) {
    let next: string | undefined
    const weekday = (dateObject(date).getUTCDay() + 6) % 7
    if (event.key === 'ArrowLeft') next = moveDays(date, -1) || date
    if (event.key === 'ArrowRight') next = moveDays(date, 1) || date
    if (event.key === 'ArrowUp') next = moveDays(date, -7) || date
    if (event.key === 'ArrowDown') next = moveDays(date, 7) || date
    if (event.key === 'Home') next = moveDays(date, -weekday) || date
    if (event.key === 'End') next = moveDays(date, 6 - weekday) || date
    if (event.key === 'PageUp' || event.key === 'PageDown') {
      const target = calendarMonthDate(date, Number(date.slice(8, 10)), (event.key === 'PageUp' ? -1 : 1) * (event.shiftKey ? 12 : 1))
      next = /^\d{4}-\d{2}-\d{2}$/.test(target) ? target : date
    }
    if (next) {
      event.preventDefault(); event.stopPropagation()
      next = clamp(next)
      focusRequested.current = true
      setActive(next); setMonth(next.slice(0, 7))
    }
  }

  return <div className="ik-date-field">
    <button {...aria} id={id} ref={trigger} type="button" className="ik-field-trigger ik-date-trigger" disabled={disabled} data-open={expanded} aria-haspopup="dialog" aria-expanded={expanded} aria-controls={popupId} aria-description={required ? 'Обязательное поле' : undefined} onClick={show} onKeyDown={event => {
      if (event.key === 'ArrowDown' && !expanded) { event.preventDefault(); show() }
      if (event.key === 'Escape' && expanded) { event.preventDefault(); event.stopPropagation(); close() }
    }}><span className={value ? '' : 'ik-date-placeholder'}>{displayDate(value)}</span><CalendarDays size={17} aria-hidden="true"/></button>
    {name && <input type="hidden" name={name} value={value} disabled={disabled}/>}
    {mounted && createPortal(<div ref={popup} id={popupId} className="ik-field-popover ik-calendar" data-field-popover="" data-open={expanded} role="dialog" aria-label={aria['aria-label'] ? 'Календарь: ' + aria['aria-label'] : 'Выбор даты'} aria-hidden={!expanded} style={position} onKeyDown={popupKey}>
      <div className="ik-calendar-head"><div className="ik-calendar-heading" id={monthId}><button type="button" className="ik-calendar-month" aria-label="Выбрать месяц" aria-expanded={view === 'months'} onClick={() => showView(view === 'months' ? 'days' : 'months')}>{months[monthNumber - 1]}<ChevronDown size={13}/></button><button type="button" className="ik-calendar-year" aria-label="Выбрать год" aria-expanded={view === 'years'} onClick={() => { setYearStart(Math.min(9988, Math.max(1, year - 5))); showView(view === 'years' ? 'days' : 'years') }}>{year}<ChevronDown size={13}/></button></div><button type="button" className="ik-calendar-close" aria-label="Закрыть календарь" onClick={() => close()}><X size={16}/></button></div>
      {view === 'days' ? <>
        <div className="ik-calendar-navigation"><button type="button" aria-label="Предыдущий месяц" disabled={!canNavigate(-1)} onClick={() => changeMonth(calendarMonthDate(first, 1, -1))}><ChevronLeft size={17}/></button><span aria-live="polite">Выберите день</span><button type="button" aria-label="Следующий месяц" disabled={!canNavigate(1)} onClick={() => changeMonth(calendarMonthDate(first, 1, 1))}><ChevronRight size={17}/></button></div>
        <div className="ik-calendar-weekdays" aria-hidden="true">{dayNames.map(day => <span key={day}>{day}</span>)}</div>
        <div className="ik-calendar-grid" role="grid" aria-labelledby={monthId}>{Array.from({ length: 6 }, (_, week) => <div role="row" className="ik-calendar-week" key={week}>{days.slice(week * 7, week * 7 + 7).map((date, index) => <div role="gridcell" key={date || index} aria-selected={date === value}>{date && <button type="button" className="ik-calendar-day" data-date={date} data-outside={date.slice(0, 7) !== month} data-selected={date === value} data-today={date === today} aria-label={longDate.format(dateObject(date))} aria-current={date === today ? 'date' : undefined} tabIndex={date === active ? 0 : -1} disabled={!inRange(date)} onClick={() => choose(date)} onKeyDown={event => dayKey(event, date)}>{Number(date.slice(8, 10))}</button>}</div>)}</div>)}</div>
      </> : view === 'months' ? <div className="ik-calendar-picks" aria-label="Месяцы">{months.map((name, index) => { const target = String(year).padStart(4, '0') + '-' + String(index + 1).padStart(2, '0'); return <button key={name} type="button" data-selected={index + 1 === monthNumber} disabled={target < min.slice(0, 7) || target > max.slice(0, 7)} onClick={() => changeMonth(target, true)}>{name.slice(0, 3)}</button> })}</div> : <>
        <div className="ik-calendar-navigation"><button type="button" aria-label="Предыдущие годы" disabled={yearStart <= Number(min.slice(0, 4))} onClick={() => setYearStart(start => Math.max(1, start - 12))}><ChevronLeft size={17}/></button><span aria-live="polite">{yearStart}–{Math.min(9999, yearStart + 11)}</span><button type="button" aria-label="Следующие годы" disabled={yearStart + 11 >= Number(max.slice(0, 4))} onClick={() => setYearStart(start => Math.min(9988, start + 12))}><ChevronRight size={17}/></button></div>
        <div className="ik-calendar-picks" aria-label="Годы">{Array.from({ length: 12 }, (_, index) => yearStart + index).filter(item => item <= 9999).map(item => <button type="button" key={item} data-selected={item === year} disabled={item < Number(min.slice(0, 4)) || item > Number(max.slice(0, 4))} onClick={() => { const next = clamp(calendarMonthDate(String(item).padStart(4, '0') + '-' + String(monthNumber).padStart(2, '0'), Number(active.slice(8, 10)))); setMonth(next.slice(0, 7)); setActive(next); showView('months') }}>{item}</button>)}</div>
      </>}
      <div className="ik-calendar-footer"><button type="button" disabled={!value} onClick={() => { onChange(''); close() }}>Очистить</button><button type="button" className="ik-calendar-today" disabled={!inRange(today)} onClick={() => choose(today)}>Сегодня<span>{displayDate(today)}</span></button></div>
    </div>, trigger.current?.closest('[role="dialog"][aria-modal="true"]')?.querySelector('[data-drawer-popover-root]') ?? document.body)}
  </div>
}
