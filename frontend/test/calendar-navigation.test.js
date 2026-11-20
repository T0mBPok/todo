import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { createCalendarWindow, calendarScrollPosition, calendarWindowRange, shiftCalendarDate } from '../src/shared/calendarScroll.js'
import { eventsOnDay, addDays, dateKey, fromKey, monthDays, moveDate, visibleRange, weekStart } from '../src/shared/calendar.js'

test('navigation preserves selected period lengths across month and year boundaries', () => {
  for (const [view, step] of [['day', 1], ['three', 3], ['week', 7]]) {
    const day = moveDate('2026-12-30', 1, view)
    assert.equal(day, dateKey(addDays(fromKey('2026-12-30'), step)))
    const range = visibleRange(day, view)
    assert.equal((new Date(range.end) - new Date(range.start)) / 86400000, step)
    assert.equal(moveDate(day, -1, view), '2026-12-30')
  }
  assert.equal(moveDate('2026-12-20', 1, 'month'), '2027-01-20')
})

test('day columns keep their width and track partial pixel movement in every timed view', () => {
  for (const view of ['day','three','week']) {
    const window = createCalendarWindow('2026-12-30',view)
    const width=1100, gutter=64
    const unit=(width-gutter)/window.visible
    const initial=window.padding*unit
    const before=calendarScrollPosition(window,initial,width,gutter)
    const partial=calendarScrollPosition(window,initial+unit*0.4,width,gutter)
    const next=calendarScrollPosition(window,initial+unit*1.1,width,gutter)
    assert.equal(partial.unit,before.unit)
    assert.equal(partial.day,before.day)
    assert.equal(next.day,dateKey(addDays(fromKey(before.day),1)))
    assert.equal(partial.shift,0)
  }
})

test('rebasing long scrolls keeps the same date at the same fractional pixel position in both directions', () => {
  for (const view of ['day','three','week','month']) {
    let window=createCalendarWindow('2026-12-30',view)
    const width=940, gutter=view==='month'?0:64
    let left=window.padding*calendarScrollPosition(window,0,width,gutter).unit
    for (const direction of [1,-1]) {
      for(let step=0;step<120;step++) {
        left+=direction*width*0.43
        const before=calendarScrollPosition(window,left,width,gutter)
        if(before.shift) {
          window={...window,start:shiftCalendarDate(window.start,before.shift,view)}
          left-=before.shift*before.unit
          const after=calendarScrollPosition(window,left,width,gutter)
          assert.equal(after.day,before.day)
          assert.ok(Math.abs((left/after.unit%1)-((left+before.shift*before.unit)/before.unit%1))<0.00001)
        }
      }
    }
    const range=calendarWindowRange(window)
    assert.ok(new Date(range.end)>new Date(range.start))
    assert.ok((new Date(range.end)-new Date(range.start))/86400000<220)
  }
})

const component = await readFile(new URL('../src/entities/tasks/TaskCalendar.vue', import.meta.url), 'utf8')
const script = component.match(/<script setup>([\s\S]*?)<\/script>/)[1].replace(/^import .*$/gm, '')
function setup(options = {}) {
  const events=[]
  const deps={
    defineProps:()=>({tasks:[],day:'2026-11-20',view:'week',...options}), defineEmits:()=> (name,value)=>events.push([name,value]),
    defineExpose:()=>{},ref:value=>({value}),computed:fn=>({get value(){return fn()}}),
    onMounted:()=>{},onUnmounted:()=>{},watch:()=>{},nextTick:async()=>{},
    setInterval:()=>0,clearInterval:()=>{},eventsOnDay,dateKey,fromKey,addDays,weekStart,monthDays,
    createCalendarWindow,calendarScrollPosition,calendarWindowRange,shiftCalendarDate,
  }
  const page=new Function(...Object.keys(deps),script+'\nreturn {horizontalWheel,grid,onScroll,windowState,getVisibleRange,horizontalPosition,unitWidth,showAllDay}')( ...Object.values(deps))
  page.grid.value={scrollLeft:2208,scrollTop:480}
  return {page,events}
}

test('wheel leaves native trackpad scrolling alone and maps Shift wheel to exact pixels', async () => {
  const {page,events}=setup()
  let prevented=false
  const wheel={deltaX:32,deltaY:0,shiftKey:false,ctrlKey:false,deltaMode:0,preventDefault(){prevented=true}}
  page.horizontalWheel(wheel)
  assert.equal(prevented,false)
  assert.equal(page.grid.value.scrollLeft,2208)
  page.horizontalWheel({...wheel,deltaX:0,deltaY:17,shiftKey:true})
  assert.equal(prevented,true)
  assert.equal(page.grid.value.scrollLeft,2225)
  assert.deepEqual(events,[])
  await page.onScroll()
  assert.ok(events.every(([name])=>name!=='navigate' && name!=='range-change'))
})

test('AI context follows the actual visible days including a partially visible trailing day', () => {
  const {page}=setup()
  const full=page.getVisibleRange()
  assert.equal((new Date(full.end)-new Date(full.start))/86400000,7)
  page.grid.value.scrollLeft+=25
  const partial=page.getVisibleRange()
  assert.equal(partial.start,full.start)
  assert.equal((new Date(partial.end)-new Date(partial.start))/86400000,8)
})

test('all-day row ignores buffered events outside the visible days', () => {
  const {page}=setup({tasks:[{id:'all-day',is_all_day:true,title:'Holiday',start:'2026-12-04',end:'2026-12-05'}]})
  page.horizontalPosition.value=21*page.unitWidth.value
  assert.equal(page.showAllDay.value,false)
  page.horizontalPosition.value=35*page.unitWidth.value
  assert.equal(page.showAllDay.value,true)
})
