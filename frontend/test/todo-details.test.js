import {test} from 'node:test'
import assert from 'node:assert/strict'
import {readFile} from 'node:fs/promises'
import {errorMessage} from '../src/shared/errors.js'
const component=await readFile(new URL('../src/entities/todos/TodoDetails.vue',import.meta.url),'utf8')
const script=component.match(/<script setup>([\s\S]*?)<\/script>/)[1].replace(/^import .*$/gm,'')
function setup({fail=false,pending=false}={}) {
  const calls=[],events=[]
  let closed=0,release
  const dependencies={ref:value=>({value}),nextTick:async()=>{},defineExpose:()=>{},
    defineEmits:()=>((name,payload)=>events.push({name,payload})),errorMessage,
    request:async(path,method,body)=>{
      calls.push({path,method,body})
      if(pending)await new Promise(resolve=>{release=resolve})
      if(fail)throw Error('Нет связи')
      return {id:'real-todo',completed:body.completed}
    }}
  const app=new Function(...Object.keys(dependencies),script+'\nreturn {open,complete,edit,dialog,error,busy}')(...Object.values(dependencies))
  app.dialog.value={showModal(){},close(){closed++}}
  return {app,calls,events,closed:()=>closed,release:()=>release()}
}
test('opening task information does not mark it complete; the button uses the real todo id',async()=>{
  const s=setup()
  await s.app.open({id:'todo:real-todo',todo_id:'real-todo',title:'Сдать работу',completed:false})
  assert.equal(s.calls.length,0)
  await s.app.complete()
  assert.deepEqual(s.calls,[{path:'/todos/real-todo/completion',method:'PATCH',body:{completed:true}}])
  assert.equal(s.closed(),1)
  assert.equal(s.events[0].name,'saved')
})
test('completed tasks can be returned to work from the information popup',async()=>{
  const s=setup()
  await s.app.open({id:'real-todo',completed:true})
  await s.app.complete()
  assert.equal(s.calls[0].body.completed,false)
})
test('failed completion keeps information open and allows retry',async()=>{
  const s=setup({fail:true})
  await s.app.open({id:'real-todo',completed:false})
  await s.app.complete()
  assert.equal(s.closed(),0)
  assert.equal(s.events.length,0)
  assert.ok(s.app.error.value)
  assert.equal(s.app.busy.value,false)
})
test('repeated taps do not send duplicate completion requests',async()=>{
  const s=setup({pending:true})
  await s.app.open({id:'real-todo',completed:false})
  const first=s.app.complete()
  await s.app.complete()
  assert.equal(s.calls.length,1)
  s.release()
  await first
})
