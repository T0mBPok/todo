import { test } from 'node:test'
import assert from 'node:assert/strict'
import { dateKey, fromKey, weekStart, monthDays, moveDate, eventsOnDay, eventPosition } from '../src/shared/calendar.js'
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
