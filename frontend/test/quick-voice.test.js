import {test} from 'node:test'
import { errorMessage } from '../src/shared/errors.js'
import assert from 'node:assert/strict'
import {readFile} from 'node:fs/promises'
const component=await readFile(new URL('../src/CalendarApp.vue',import.meta.url),'utf8')
const script=component.match(/<script setup>([\s\S]*?)<\/script>/)[1].replace(/^import .*$/gm,'')
function setup({response,error,confirmError,voiceFactory}={}) {
  let callbacks, toggles=0,cancels=0,confirms=0,requests=0
  const ref=value=>({value}), computed=get=>({get value(){return get()}})
  const hook={supported:true,listening:ref(false),processing:ref(false),starting:ref(false),audioUrl:ref(''),rawTranscript:ref(''),engineName:ref(''),elapsed:ref(0),recordSeconds:ref(0),toggle:async()=>{toggles++;hook.listening.value=!hook.listening.value},cancel:()=>{cancels++;hook.listening.value=false}}
  const deps={errorMessage,defineProps:()=>({refreshToken:0}),ref,computed,watch:()=>{},nextTick:async()=>{},onMounted:()=>{},window:{innerWidth:1280},
    useVoiceInput:options=>{callbacks=options;return voiceFactory ? voiceFactory(options) : hook},
    request:async path=>{if(path==='/todos')return [];requests++;if(error)throw Error(error);return path.endsWith('/execute')?{note:'Готово',tasks:[]}:path.endsWith('/clear-calendar')?{note:'Календарь очищен.'}:typeof response === 'function' ? response(requests) : response},
    listTasks:async()=>[],visibleRange:()=>({}),localDate:value=>new Date(value).toISOString().slice(0,16),
    dateKey:()=>'',fromKey:()=>new Date(),monthDays:()=>[],
    confirmPlan:async()=>{confirms++;if(confirmError)throw Error(confirmError);return [{id:'saved',start:'2026-10-20T18:00:00Z'}]}}
  const expose='return {quickMic,cancelQuick,voiceOpen,quickMode,text,message,command,plan,autoSave,busy,generate,planEditor,clearCalendarDraft,confirmCalendarClear,choices,excludeDeletion}'
  const app=new Function(...Object.keys(deps),script+'\n'+expose)(...Object.values(deps))
  return {app,hook,status:()=>({toggles,cancels,confirms,requests}),async finish(text){hook.listening.value=false;hook.rawTranscript.value=text;app.text.value=text;await callbacks.onComplete()},async transcribe(corrected,raw=corrected){hook.listening.value=false;hook.rawTranscript.value=raw;app.text.value=corrected;await callbacks.onComplete()},fail:value=>callbacks.onError(value)}
}
test('quick recording starts immediately without opening the panel, second click stops it',async()=>{
  const {app,hook,status}=setup();await app.quickMic()
  assert.equal(hook.listening.value,true);assert.equal(app.voiceOpen.value,false)
  await app.quickMic();assert.equal(hook.listening.value,false);assert.equal(status().toggles,2)
})
test('successful quick plan saves and keeps the calendar visible',async()=>{
  const s=setup({response:{kind:'plan',plan:{id:'plan',tasks:[{start:'2026-10-20T18:00:00Z'}]}}})
  await s.app.quickMic();await s.finish('Завтра тренировка в шесть')
  assert.equal(s.status().confirms,1);assert.equal(s.app.voiceOpen.value,true)
  assert.equal(s.app.text.value,'Завтра тренировка в шесть')
  assert.match(s.app.message.value,/добавлены в календарь/)
})
test('flagged plans open the editable preview before saving', async () => {
  const task = { start: '2026-10-20T18:00:00Z' }
  for (const plan of [{ tasks: [task, task], review: [{ task_index: 0 }] }, { tasks: [task], review: [{ task_index: 0 }] }]) {
    const s = setup({ response: { kind: 'plan', plan: { id: 'plan', ...plan } } })
    await s.app.quickMic()
    await s.finish('Длинная команда')
    assert.equal(s.status().confirms, 0)
    assert.equal(s.app.text.value, 'Длинная команда')
    assert.equal(s.app.voiceOpen.value, true)
    let saved = false
    s.app.planEditor.value = { save: async () => { saved = true } }
    await s.finish('сохрани')
    assert.equal(saved, true)
    assert.equal(s.status().confirms, 0)
  }
})
test('clear calendar opens confirmation and waits for its button even with auto save', async () => {
  const s = setup({ response: { kind: 'calendar_clear', id: 'clear', count: 230, note: 'Удалить всё?' } })
  await s.app.quickMic()
  await s.finish('Очисти календарь')
  assert.equal(s.app.clearCalendarDraft.value.count, 230)
  assert.equal(s.app.voiceOpen.value, true)
  await s.finish('подтверждаю')
  assert.equal(s.status().requests, 1)
  await s.app.confirmCalendarClear()
  assert.equal(s.status().requests, 2)
  assert.equal(s.app.clearCalendarDraft.value, null)
  assert.match(s.app.message.value, /Календарь очищен/)
})
test('clear calendar requires a scope for recurring events before confirmation', async () => {
  const s = setup({ response: { kind: 'calendar_clear', id: 'clear', count: 230,
    series: [{ series_id: 'series', occurrence_start: '2026-10-20T18:00:00Z' }] } })
  await s.app.quickMic()
  await s.finish('Очисти календарь')
  await s.finish('Подтверждаю очистку календаря.')
  assert.equal(s.status().requests, 1)
  await s.finish('По одному повторению.')
  assert.equal(s.status().requests, 1)
  await s.finish('Подтверждаю очистку календаря.')
  assert.equal(s.status().requests, 2)
  assert.equal(s.app.clearCalendarDraft.value, null)
})
test('a new global delete command does not become a scope answer to a pending edit', async () => {
  const pending = { kind: 'command', id: 'edit', operations: [
    { requires_confirmation: true, instruction: { operation: 'update', scope: 'unspecified' },
      candidates: [{ id: 'series', recurrence: {} }] }
  ] }
  const s = setup({ response: calls => calls === 1 ? pending : { kind: 'calendar_clear', id: 'clear', count: 2 } })
  await s.app.quickMic()
  await s.finish('Перенеси тренировку')
  await s.finish('Снеси нахуй все события')
  assert.equal(s.status().requests, 2)
  assert.equal(s.app.clearCalendarDraft.value.id, 'clear')
})
test('the explicit spoken confirmation can also clear the calendar', async () => {
  const s = setup({ response: { kind: 'calendar_clear', id: 'clear', count: 230 } })
  await s.app.quickMic()
  await s.finish('Очисти календарь')
  await s.finish('Подтверждаю очистку календаря.')
  assert.equal(s.status().requests, 2)
  assert.equal(s.app.clearCalendarDraft.value, null)
})
test('ambiguous command opens panel without executing it',async()=>{
  const s=setup({response:{kind:'command',id:'draft',note:'Выбери',operations:[{instruction:{scope:'unspecified'},candidates:[{id:'a'},{id:'b'}]}]}})
  await s.app.quickMic();await s.finish('Удали тренировку')
  assert.equal(s.app.voiceOpen.value,true);assert.equal(s.app.command.value.id,'draft')
})
test('manual confirmation preference opens plan after quick transcription',async()=>{
  const s=setup({response:{kind:'plan',plan:{id:'plan',tasks:[{start:'2026-10-20T18:00:00Z'}]}}})
  s.app.autoSave.value=false;await s.app.quickMic();await s.finish('Завтра тренировка')
  assert.equal(s.app.voiceOpen.value,true);assert.equal(s.status().confirms,0)
})
test('command failure and microphone failure reveal the panel',async()=>{
  const s=setup({error:'Не нашёл задачу'});await s.app.quickMic();await s.finish('Перенеси встречу')
  assert.equal(s.app.voiceOpen.value,true);assert.match(s.app.message.value,/Не нашёл/)
  const mic=setup();await mic.app.quickMic();mic.fail('Доступ к микрофону запрещён')
  assert.equal(mic.app.voiceOpen.value,true)
})
test('quick cancellation releases recording without opening the panel',async()=>{
  const s=setup();await s.app.quickMic();s.app.cancelQuick()
  assert.equal(s.hook.listening.value,false);assert.equal(s.status().cancels,1)
  assert.equal(s.app.voiceOpen.value,false)
})

test('bulk deletion waits for explicit confirmation even with auto save',async()=>{
  const s=setup({response:{kind:'command',id:'bulk',note:'Сохранить пару',operations:[{requires_confirmation:true,instruction:{scope:'occurrence'},candidates:[{id:'a'}]}]}})
  await s.app.quickMic();await s.finish('Удали в субботу всё кроме пары')
  assert.equal(s.status().requests,1);assert.equal(s.app.voiceOpen.value,true)
  await s.finish('только это событие')
  assert.equal(s.status().requests,1)
  await s.finish('подтверждаю')
  assert.equal(s.status().requests,2);assert.equal(s.app.command.value,null)
})

test('mixed replacement retains both additions and waits for confirmation',async()=>{
  const operations=['delete','delete','create','create'].map((operation,index)=>({requires_confirmation:true,instruction:{operation,scope:'occurrence'},candidates:[{id:String(index),title:'Действие '+index,start:'2026-10-28T07:00:00Z'}]}))
  const s=setup({response:{kind:'command',id:'replacement',note:'Проверить четыре действия',operations}})
  await s.app.quickMic();await s.finish('Убери пару и прототип, вместо них хакатон в 14 и баскетбол в 19')
  assert.equal(s.app.command.value.operations.length,4)
  assert.equal(s.app.command.value.operations.at(-1).instruction.operation,'create')
  assert.equal(s.status().requests,1);assert.equal(s.app.voiceOpen.value,true)
  await s.finish('подтверждаю');assert.equal(s.status().requests,2)
})


test('AI transcript stays editable and automatically sends the corrected command once',async()=>{
  const s=setup({response:{kind:'plan',plan:{id:'plan',tasks:[{start:'2026-10-20T18:00:00Z'}]}}})
  await s.app.quickMic()
  await s.transcribe('Завтра тренировка с 18:00 до 19:00.','Завтра тренеровка с 18:0 до 19:0.')
  assert.equal(s.app.text.value,'Завтра тренировка с 18:00 до 19:00.')
  assert.equal(s.app.voiceOpen.value,true)
  assert.equal(s.hook.rawTranscript.value,'Завтра тренеровка с 18:0 до 19:0.')
  assert.equal(s.status().requests,1)
  assert.equal(s.status().confirms,1)
})


test('several confident events auto-save after speech without an extra submit',async()=>{
  const tasks=[{start:'2026-10-20T18:00:00Z'},{start:'2026-10-21T08:00:00Z'}]
  const s=setup({response:{kind:'plan',plan:{id:'plan',tasks,review:[]}}})
  await s.transcribe('Завтра тренировка в 18:00. Послезавтра созвон в 08:00.')
  assert.equal(s.status().requests,1)
  assert.equal(s.status().confirms,1)
  assert.equal(s.app.plan.value,null)
  assert.equal(s.app.text.value,'Завтра тренировка в 18:00. Послезавтра созвон в 08:00.')
})


test('final AI transcript appears in the input while success status stays short',async()=>{
  const corrected='В четверг военная кафедра с 08:00 до 17:00.'
  const s=setup({response:{kind:'plan',plan:{id:'plan',tasks:[{start:'2026-10-22T08:00:00Z'}],
    normalized_text:corrected,note:'Понял: Военная кафедра. Нормализованный текст: '+corrected}}})
  await s.transcribe('В четверг там кафедра с восьми до пяти.')
  assert.equal(s.app.text.value,corrected)
  assert.equal(s.app.message.value,'Задачи добавлены в календарь: 1.')
  assert.doesNotMatch(s.app.message.value,/Нормализованный|кафедра/)
  assert.equal(s.status().confirms,1)
})


test('bulk delete excludes a chip and sends one confirmation for the remaining list',async()=>{
 const operations=[0,1,2].map(i=>({bulk_delete:true,requires_confirmation:true,instruction:{operation:'delete',scope:'occurrence'},candidates:[{id:String(i),title:'Event '+i,start:'2026-11-23T08:00:00Z'}]}))
 const s=setup({response:{kind:'command',id:'bulk',operations}})
 await s.finish('Удали все события следующей недели')
 s.app.excludeDeletion(1)
 assert.equal(s.app.choices.value[1].skip,true)
 assert.equal(s.status().requests,1)
 await s.finish('подтверждаю')
 assert.equal(s.status().requests,2)
 assert.equal(s.app.command.value,null)
})


test('real recorder completion automatically transcribes, prepares and saves without a submit click',async()=>{
 const source=(await readFile(new URL('../src/features/voice/useVoiceInput.js',import.meta.url),'utf8'))
   .replace("import { ref, onUnmounted } from 'vue'","const ref=value=>({value}); const onUnmounted=()=>{}")
   .replace("'../../shared/api'",JSON.stringify(new URL('../src/shared/api.js',import.meta.url).href))
 const {useVoiceInput}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'))
 let recorder,uploads=0
 const oldNavigator=Object.getOwnPropertyDescriptor(globalThis,'navigator')
 const oldWindow=globalThis.window,oldRecorder=globalThis.MediaRecorder,oldFetch=globalThis.fetch
 class Recorder {
   static isTypeSupported(){return true}
   constructor(){recorder=this;this.mimeType='audio/webm';this.state='inactive'}
   start(){this.state='recording'}
   stop(){this.state='inactive';this.ondataavailable({data:new Blob(['audio'])});this.finished=this.onstop()}
 }
 try {
   Object.defineProperty(globalThis,'navigator',{configurable:true,value:{mediaDevices:{getUserMedia:async()=>({getTracks:()=>[{stop(){}}]})}}})
   globalThis.window={MediaRecorder:Recorder};globalThis.MediaRecorder=Recorder
   globalThis.fetch=async(url)=>{uploads++;assert.equal(url,'/api/voice/transcribe');return {ok:true,json:async()=>({text:'Завтра тренировка в 18:00.',raw_text:'завтра тренеровка в 18:00'})}}
   const s=setup({voiceFactory:useVoiceInput,response:{kind:'plan',plan:{id:'plan',tasks:[{start:'2026-11-21T11:00:00Z'}],review:[]}}})
   await s.app.quickMic()
   await s.app.quickMic()
   await recorder.finished
   assert.equal(uploads,1)
   assert.equal(s.status().requests,1)
   assert.equal(s.status().confirms,1)
   assert.equal(s.app.text.value,'Завтра тренировка в 18:00.')
   assert.equal(s.app.busy.value,false)
 } finally {
   if(oldNavigator)Object.defineProperty(globalThis,'navigator',oldNavigator);else delete globalThis.navigator
   globalThis.window=oldWindow;globalThis.MediaRecorder=oldRecorder;globalThis.fetch=oldFetch
 }
})
