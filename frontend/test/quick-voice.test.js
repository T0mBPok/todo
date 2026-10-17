import {test} from 'node:test'
import assert from 'node:assert/strict'
import {readFile} from 'node:fs/promises'
const component=await readFile(new URL('../src/App.vue',import.meta.url),'utf8')
const script=component.match(/<script setup>([\s\S]*?)<\/script>/)[1].replace(/^import .*$/gm,'')
function setup({response,error,confirmError}={}) {
  let callbacks, toggles=0,cancels=0,confirms=0,requests=0
  const ref=value=>({value}), computed=get=>({get value(){return get()}})
  const hook={supported:true,listening:ref(false),processing:ref(false),starting:ref(false),audioUrl:ref(''),rawTranscript:ref(''),engineName:ref(''),elapsed:ref(0),recordSeconds:ref(0),toggle:async()=>{toggles++;hook.listening.value=!hook.listening.value},cancel:()=>{cancels++;hook.listening.value=false}}
  const deps={ref,computed,watch:()=>{},nextTick:async()=>{},onMounted:()=>{},window:{innerWidth:1280},
    useVoiceInput:options=>{callbacks=options;return hook},
    request:async path=>{requests++;if(error)throw Error(error);return path.endsWith('/execute')?{note:'Готово',tasks:[]}:response},
    listTasks:async()=>[],visibleRange:()=>({}),localDate:value=>new Date(value).toISOString().slice(0,16),
    dateKey:()=>'',fromKey:()=>new Date(),monthDays:()=>[],
    confirmPlan:async()=>{confirms++;if(confirmError)throw Error(confirmError);return [{id:'saved',start:'2026-10-20T18:00:00Z'}]}}
  const expose='return {quickMic,cancelQuick,voiceOpen,quickMode,text,message,command,plan,autoSave,busy,generate}'
  const app=new Function(...Object.keys(deps),script+'\n'+expose)(...Object.values(deps))
  return {app,hook,status:()=>({toggles,cancels,confirms,requests}),async finish(text){hook.listening.value=false;hook.rawTranscript.value=text;app.text.value=text;await callbacks.onComplete()},fail:value=>callbacks.onError(value)}
}
test('quick recording starts immediately without opening the panel, second click stops it',async()=>{
  const {app,hook,status}=setup();await app.quickMic()
  assert.equal(hook.listening.value,true);assert.equal(app.voiceOpen.value,false)
  await app.quickMic();assert.equal(hook.listening.value,false);assert.equal(status().toggles,2)
})
test('successful quick plan saves and keeps the calendar visible',async()=>{
  const s=setup({response:{kind:'plan',plan:{id:'plan',tasks:[{start:'2026-10-20T18:00:00Z'}]}}})
  await s.app.quickMic();await s.finish('Завтра тренировка в шесть')
  assert.equal(s.status().confirms,1);assert.equal(s.app.voiceOpen.value,false)
  assert.match(s.app.message.value,/Добавлено в календарь/)
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
