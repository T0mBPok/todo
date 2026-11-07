<script setup>
import {ref,watch,onMounted,onUnmounted} from 'vue'
import {request} from '../../shared/api'
const props=defineProps({tasks:Array}),emit=defineEmits(['applied'])
const result=ref(null),busy=ref(false),error=ref(''),agreed=ref({}),dismissed=ref([])
let signature='',timer,interval,disposed=false,pending=false
function format(value){return new Date(value).toLocaleString('ru-RU',{weekday:'short',day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'})}
async function scan(force=false){
 if(busy.value){pending=true;return}
 busy.value=true;error.value=''
 try{
  const start=new Date();start.setHours(0,0,0,0);const end=new Date(start);end.setDate(end.getDate()+14)
  const events=await request('/tasks?'+new URLSearchParams({start:start.toISOString(),end:end.toISOString()}))
  const key=JSON.stringify(events)
  if(!force&&key===signature)return
  result.value=null;dismissed.value=[];agreed.value={}
  const value=await request('/balance/scan','POST')
  if(!disposed){result.value=value;signature=key}
 }catch(e){if(!disposed)error.value=e.message}
 finally{busy.value=false;if(pending&&!disposed){pending=false;schedule()}}
}
function schedule(){clearTimeout(timer);timer=setTimeout(()=>scan(),1500)}
async function apply(index){busy.value=true;error.value='';try{const value=await request('/balance/'+result.value.id+'/apply','POST',{proposals:[index],coordination_confirmed:!!agreed.value[index]});result.value=null;signature='';emit('applied',value.note);pending=true}catch(e){error.value=e.message;result.value=null;signature=''}finally{busy.value=false;if(pending){pending=false;schedule()}}}
watch(()=>props.tasks,schedule)
onMounted(()=>{scan();interval=setInterval(()=>scan(),60000)})
onUnmounted(()=>{disposed=true;clearTimeout(timer);clearInterval(interval)})
</script>
<template><aside class="ai-suggestions" aria-label="Предложения ИИ">
 <header><div><span class="ai-spark">✧</span><h2>Предложения ИИ</h2></div><button :disabled="busy" aria-label="Обновить предложения ИИ" @click="scan(true)">↻</button></header>
 <p class="ai-caption">Смотрю расписание на 7 дней вперёд и ищу, где можно разгрузить день.</p>
 <details class="ai-criteria"><summary>Как оценивается нагрузка?</summary><p>Учитываю часы занятости, плотные блоки и короткие перерывы. Два дела утром и вечером сами по себе не считаются перегрузкой. Сравниваю оба дня до и после переноса: требуется снижение условной оценки нагрузки минимум на 10%. Простая перестановка одинаковой нагрузки не подходит.</p></details>
 <p v-if="busy" role="status" class="ai-working">◌ Анализирую расписание…</p>
 <div v-if="error" role="alert"><p>{{error}}</p><button :disabled="busy" @click="scan(true)">Повторить анализ</button></div>
 <template v-if="result&&!busy">
  <p class="ai-summary">{{result.summary}}</p>
  <template v-for="(proposal,i) in result.proposals" :key="i"><article v-if="!dismissed.includes(i)" class="ai-move">
   <span class="ai-move-label">Можно разгрузить день</span><h3>{{proposal.snapshot.title}}</h3>
   <div class="ai-old-time">{{format(proposal.snapshot.start)}}</div><div class="ai-new-time">↳ {{format(proposal.new_start)}}</div>
   <p>{{proposal.reason}}</p><small v-if="proposal.snapshot.recurrence">Только это повторение, остальные останутся на месте.</small>
   <label v-if="proposal.needs_agreement"><input v-model="agreed[i]" type="checkbox">Новое время согласовано с участниками</label>
   <div class="ai-actions"><button class="ai-accept" :disabled="proposal.needs_agreement&&!agreed[i]" @click="apply(i)">Перенести</button><button @click="dismissed.push(i)">Оставить</button></div>
  </article></template>
  <p v-if="result.proposals.length&&dismissed.length===result.proposals.length" class="ai-caption">Оставили расписание как есть.</p>
 </template>
 <footer>Пары и фиксированные события сохраняю. Переносы — только с твоего согласия.</footer>
</aside></template>
