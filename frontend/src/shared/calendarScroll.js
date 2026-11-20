import { addDays, dateKey, fromKey, monthDays, weekStart } from './calendar.js'

export function shiftCalendarDate(date, amount, view) {
  if (view !== 'month') return addDays(date, amount)
  return new Date(date.getFullYear(), date.getMonth() + amount, 1)
}

export function createCalendarWindow(day, view) {
  const visible = view === 'week' ? 7 : view === 'three' ? 3 : 1
  const padding = view === 'month' ? 2 : visible * 3
  const anchor = view === 'week' ? weekStart(fromKey(day)) : fromKey(day)
  return { view, visible, padding, length: view === 'month' ? 5 : visible * 7,
    start: shiftCalendarDate(anchor, -padding, view) }
}

export function calendarWindowRange(window) {
  const last = shiftCalendarDate(window.start, window.length - 1, window.view)
  const start = window.view === 'month' ? monthDays(window.start)[0] : window.start
  const end = window.view === 'month' ? addDays(monthDays(last)[41], 1) : addDays(last, 1)
  return { start: start.toISOString(), end: end.toISOString() }
}

export function calendarScrollPosition(window, left, width, gutter = 0) {
  const unit = window.view === 'month' ? width : (width - gutter) / window.visible
  const offset = Math.max(0, left) / Math.max(1, unit)
  const index = Math.floor(offset + 0.00001)
  const shift = window.view === 'month'
    ? offset < 0.75 ? -2 : offset > 3.25 ? 2 : 0
    : offset < window.visible ? -window.padding : offset > window.visible * 5 ? window.padding : 0
  return { unit, index, shift, day: dateKey(shiftCalendarDate(window.start, index, window.view)) }
}
