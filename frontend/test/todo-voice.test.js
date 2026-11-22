import {test} from 'node:test'
import assert from 'node:assert/strict'
import {readFile} from 'node:fs/promises'
import {errorMessage} from '../src/shared/errors.js'
const component=await readFile(new URL('../src/entities/todos/TodoVoicePanel.vue',import.meta.url),'utf8')
const script=component.match(/<script setup>([\s\S]*?)<\/script>/)[1].replace(/^import .*$/gm,'')
function setup({confirmation=false,error=false}={}){
 let hook;const calls=[],changes=[]
 const ref=value=>({value})
 const task={id:'todo',title:'Сделать адаптив',scheduled_date:'2026-11-27',scheduled_at:'2026-11-27T11:00:00Z'}
 const deps={ref,errorMessage,defineEmits:()=>((name,payload)=>changes.push({name,payload})),
  useVoiceInput:options=>{hook=options;return {supported:true,listening:ref(false),starting:ref(false),processing:ref(false),toggle:async()=>{},cancel:()=>{},recordSeconds:ref(0),audioUrl:ref(''),rawTranscript:ref('')}},
  request:async(path,method,body)=>{calls.push({path,method,body});if(error)throw Error('Не удалось разобрать задачи');return path.endsWith('/prepare')?{id:'draft',note:'Добавить адаптив',requires_confirmation:confirmation,operations:[]}:{note:'Готово',tasks:[task]}}}
 const app=new Function(...Object.keys(deps),script+'\nreturn {text,prepare,execute,draft,message,saved,busy}')(...Object.values(deps))
 return {app,calls,changes,async finish(){app.text.value='Сделать адаптив 27-го числа в шесть вечера';await hook.onComplete()}}
}
test('task transcription automatically prepares and executes once with user timezone',async()=>{
 const s=setup();await s.finish()
 assert.deepEqual(s.calls.map(c=>c.path),['/todos/commands/prepare','/todos/commands/draft/execute'])
 assert.equal(s.calls[0].body.timezone,Intl.DateTimeFormat().resolvedOptions().timeZone)
 assert.equal(s.app.saved.value.length,1);assert.equal(s.changes[0].name,'changed');assert.equal(s.changes[0].payload[0].scheduled_date,'2026-11-27')
 assert.match(s.app.text.value,/шесть вечера/)
 await s.app.execute();assert.equal(s.calls.length,2)
})
test('ambiguous scheduling or deletion waits for one confirmation',async()=>{
 const s=setup({confirmation:true});await s.finish()
 assert.equal(s.calls.length,1);assert.ok(s.app.draft.value);assert.equal(s.changes.length,0)
 await s.app.execute();assert.equal(s.calls.length,2);assert.equal(s.app.draft.value,null)
})
test('failed parsing does not execute or change calendar',async()=>{
 const s=setup({error:true});await s.finish()
 assert.equal(s.calls.length,1);assert.equal(s.changes.length,0);assert.equal(s.app.busy.value,false);assert.ok(s.app.text.value)
})
