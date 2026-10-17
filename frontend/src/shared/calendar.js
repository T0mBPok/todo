export function dateKey(value) {
  const d = new Date(value)
  return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`
}
export const fromKey = key => new Date(key + 'T00:00:00')
export function addDays(value, count) { const d = new Date(value); d.setDate(d.getDate()+count); return d }
export function weekStart(value) { const d = new Date(value); d.setHours(0,0,0,0); return addDays(d, -((d.getDay()+6)%7)) }
export function monthDays(value) { const d = new Date(value); d.setDate(1); const first = weekStart(d); return Array.from({length:42},(_,i)=>addDays(first,i)) }
export function moveDate(key, amount, view) {
  const d = fromKey(key)
  if (view === 'month') { const day=d.getDate(); d.setDate(1); d.setMonth(d.getMonth()+amount); d.setDate(Math.min(day,new Date(d.getFullYear(),d.getMonth()+1,0).getDate())) }
  else d.setDate(d.getDate() + amount*(view==='week'?7:1))
  return dateKey(d)
}
export function eventsOnDay(tasks, day) {
  const start = fromKey(day), end = addDays(start,1)
  return tasks.filter(t=>new Date(t.start)<end && new Date(t.end)>start).sort((a,b)=>new Date(a.start)-new Date(b.start))
}
export function eventPosition(task, day) {
  const base=fromKey(day), next=addDays(base,1)
  const start=new Date(Math.max(new Date(task.start),base)), end=new Date(Math.min(new Date(task.end),next))
  const minute=d=>d.getHours()*60+d.getMinutes()
  return { top: minute(start)/1440*100+'%', height: Math.max(1.15, ((+end===+next?1440:minute(end))-minute(start))/1440*100)+'%' }
}

export function visibleRange(day, view) {
  const selected=fromKey(day)
  const first=view==='month'?monthDays(selected)[0]:view==='week'?weekStart(selected):selected
  const last=addDays(first,view==='month'?42:view==='week'?7:1)
  return {start:first.toISOString(),end:last.toISOString()}
}
