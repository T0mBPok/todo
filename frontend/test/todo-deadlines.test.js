import {test} from 'node:test'
import assert from 'node:assert/strict'
import {readFile} from 'node:fs/promises'
import {todoDeadlineLabel,todoOverdue,todoDisplayTitle} from '../src/entities/todos/calendar.js'
import {errorMessage} from '../src/shared/errors.js'

test('a date-only deadline lasts through the end of its day in the task timezone',()=>{
  const task={deadline_date:'2026-11-27',timezone:'Asia/Tomsk'}
  assert.equal(todoOverdue(task,new Date('2026-11-27T16:59:59Z')),false)
  assert.equal(todoOverdue(task,new Date('2026-11-27T17:00:00Z')),true)
  assert.equal(todoOverdue({...task,completed:true},new Date('2026-11-28T17:00:00Z')),false)
  assert.ok(todoDeadlineLabel(task))
})
test('an exact deadline is evaluated by its instant, independently of the planned day',()=>{
  const task={scheduled_date:'2026-11-25',deadline_date:'2026-11-27',deadline_at:'2026-11-27T11:00:00Z'}
  assert.equal(todoOverdue(task,new Date('2026-11-27T10:59:59Z')),false)
  assert.equal(todoOverdue(task,new Date('2026-11-27T11:00:01Z')),true)
  assert.equal(todoDeadlineLabel({}), '')
})
test('the editor sends deadline and planned day as independent values',async()=>{
  const component=await readFile(new URL('../src/entities/todos/TodoEditor.vue',import.meta.url),'utf8')
  const script=component.match(/<script setup>([\s\S]*?)<\/script>/)[1].replace(/^import .*$/gm,'')
  const calls=[]
  const deps={ref:value=>({value}),nextTick:async()=>{},defineEmits:()=>()=>{},defineExpose:()=>{},errorMessage,todoDisplayTitle,
    localDate:value=>new Date(value).toISOString().slice(0,16),
    request:async(path,method,body)=>{calls.push(body);return {id:'task',...body}}}
  const app=new Function(...Object.keys(deps),script+'\nreturn {open,save,date,time,deadlineDate,deadlineTime,dialog}')(...Object.values(deps))
  app.dialog.value={showModal(){},close(){}}
  await app.open({id:'task',title:'Отчёт',scheduled_date:'2026-11-25'})
  app.deadlineDate.value='2026-11-27'
  app.deadlineTime.value='18:00'
  await app.save()
  assert.equal(calls[0].scheduled_date,'2026-11-25')
  assert.equal(calls[0].scheduled_at,null)
  assert.equal(calls[0].deadline_date,'2026-11-27')
  assert.ok(calls[0].deadline_at)
  app.deadlineDate.value=''
  app.deadlineTime.value=''
  await app.save()
  assert.equal(calls[1].deadline_date,null)
  assert.equal(calls[1].deadline_at,null)
})
