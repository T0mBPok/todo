import {test} from 'node:test'
import assert from 'node:assert/strict'
import {todoCalendarItems,todoScheduleLabel} from '../src/entities/todos/calendar.js'
import {eventsOnDay} from '../src/shared/calendar.js'

test('dated tasks project into calendar without duplicating unscheduled tasks',()=>{
 const source=[{id:'a',title:'Без даты'},{id:'b',title:'Отчёт',scheduled_date:'2026-11-27',completed:false},{id:'c',title:'Адаптив',scheduled_date:'2026-11-27',scheduled_at:'2026-11-27T11:00:00Z',completed:true}]
 const items=todoCalendarItems(source)
 assert.equal(items.length,2);assert.equal(items[0].id,'todo:b');assert.equal(items[0].todo_id,'b');assert.equal(items[0].is_all_day,true)
 assert.equal(items[1].is_all_day,false);assert.equal(items[1].completed,true)
 assert.equal(eventsOnDay(items,'2026-11-27').length,2);assert.equal(eventsOnDay(items,'2026-11-28').length,0)
 assert.equal(source[1].start,undefined)
 assert.equal(+new Date(items[1].end)-+new Date(items[1].start),30*60000)
})
test('date-only scheduling stays a calendar date in every browser timezone',()=>{
 for(const tz of ['Asia/Tomsk','Europe/Moscow','America/New_York']){
  process.env.TZ=tz
  const [item]=todoCalendarItems([{id:'x',scheduled_date:'2026-11-27'}])
  assert.equal(eventsOnDay([item],'2026-11-27').length,1)
  assert.match(todoScheduleLabel(item),/27/)
 }
})


test('calendar and list titles omit schedule suffixes but preserve meaningful dates',async()=>{
 const {todoDisplayTitle}=await import('../src/entities/todos/calendar.js')
 const scheduled={scheduled_date:'2026-11-27',scheduled_at:'2026-11-27T06:00:00+07:00'}
 assert.equal(todoDisplayTitle({...scheduled,title:'Пробежка 27 ноября в 6 утра'}),'Пробежка')
 assert.equal(todoDisplayTitle({...scheduled,title:'Пробежка в 06:00'}),'Пробежка')
 assert.equal(todoDisplayTitle({...scheduled,title:'Отчёт за 27 ноября'}),'Отчёт за 27 ноября')
 assert.equal(todoDisplayTitle({...scheduled,title:'Купить 6 стульев'}),'Купить 6 стульев')
})
