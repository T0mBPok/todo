import { test } from 'node:test'
import assert from 'node:assert/strict'
import { dateKey, fromKey, weekStart, monthDays, moveDate, eventsOnDay, eventPosition, positionedEvents } from '../src/shared/calendar.js'
test('weeks start Monday and cross year boundary',()=>{
  assert.equal(dateKey(weekStart(fromKey('2026-10-18'))),'2026-10-12')
  assert.equal(moveDate('2026-12-29',1,'week'),'2027-01-05')
})
test('month navigation clamps dates',()=>{
  assert.equal(moveDate('2026-01-31',1,'month'),'2026-02-28')
  assert.equal(monthDays(fromKey('2026-10-16')).length,42)
})
test('overnight events are clipped and midnight boundaries are half-open',()=>{
  const task={start:'2026-10-17T23:00:00',end:'2026-10-18T01:00:00'}
  assert.equal(eventsOnDay([task],'2026-10-18').length,1)
  assert.equal(eventsOnDay([{start:'2026-10-17T23:00:00',end:'2026-10-18T00:00:00'}],'2026-10-18').length,0)
  assert.ok(Math.abs(parseFloat(eventPosition(task,'2026-10-18').height)-100/24)<0.01)
  assert.equal(eventPosition(task,'2026-10-18').top,'0%')
})


import { taskPayload } from '../src/shared/api.js'
test('task payload keeps a recurrence rule',()=>{
  const recurrence={frequency:'weekly',timezone:'Europe/Berlin'}
  const payload=taskPayload({title:'Спорт',start:'2026-10-20T18:00',end:'2026-10-20T19:00',recurrence})
  assert.deepEqual(payload.recurrence,recurrence)
})
test('manual recurrence control creates or clears the rule',()=>{
  const task={title:'Спорт',start:'2026-10-20T18:00',end:'2026-10-20T19:00'}
  assert.equal(taskPayload({...task,repeat:'weekly'}).recurrence.frequency,'weekly')
  assert.equal(taskPayload({...task,repeat:'none'}).recurrence,null)
})

test('all-day events stay on their calendar dates', () => {
  const event = {is_all_day: true, start: '2026-10-17T00:00:00Z', end: '2026-10-19T00:00:00Z'}
  assert.deepEqual(eventsOnDay([event], '2026-10-16'), [])
  assert.deepEqual(eventsOnDay([event], '2026-10-17'), [event])
  assert.deepEqual(eventsOnDay([event], '2026-10-18'), [event])
  assert.deepEqual(eventsOnDay([event], '2026-10-19'), [])
})
test('overlapping timed events use separate columns', () => {
  const event = (start, end) => ({start: '2026-10-17T' + start, end: '2026-10-17T' + end})
  const cards = positionedEvents([event('09:00', '10:00'), event('09:30', '11:00'), event('11:00', '12:00')], '2026-10-17')
  assert.notEqual(cards[0].style.left, cards[1].style.left)
  assert.equal(cards[2].style.left, undefined)
})


test('17:00 event shares the day with one ending at 17:30 without shifting either', () => {
  const tasks = [
    {id:'first',start:'2026-11-26T16:00:00',end:'2026-11-26T17:30:00'},
    {id:'second',start:'2026-11-26T17:00:00',end:'2026-11-26T18:00:00'},
  ]
  const cards = positionedEvents(tasks,'2026-11-26')
  assert.deepEqual(cards.map(card=>[card.column,card.columns]),[[0,2],[1,2]])
  assert.equal(cards[0].task.end,tasks[0].end)
  assert.equal(cards[1].task.start,tasks[1].start)
})

test('overlapping cards expand into columns that are free for their entire duration', () => {
  const task = (id,start,end) => ({id,start:'2026-11-26T'+start,end:'2026-11-26T'+end})
  const cards = positionedEvents([
    task('long','09:00','10:00'),task('first','09:00','09:30'),
    task('short','09:00','09:15'),task('later','09:30','10:00'),
    task('after','10:00','11:00')
  ],'2026-11-26')
  const later=cards.find(card=>card.task.id==='later')
  assert.equal(later.column,1)
  assert.equal(later.columns,3)
  assert.equal(later.span,2)
  assert.equal(cards.find(card=>card.task.id==='after').columns,1)
})

test('equal-start events have a stable layout regardless of API response order', () => {
  const tasks=[{id:'short',start:'2026-11-26T09:00:00',end:'2026-11-26T09:30:00'},
    {id:'long',start:'2026-11-26T09:00:00',end:'2026-11-26T10:00:00'}]
  const layout=items=>positionedEvents(items,'2026-11-26').map(card=>[card.task.id,card.column])
  assert.deepEqual(layout(tasks),layout([...tasks].reverse()))
  assert.equal(layout(tasks)[0][0],'long')
})
