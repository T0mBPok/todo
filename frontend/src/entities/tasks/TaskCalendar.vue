<script setup>
import { computed, ref, onMounted, onUnmounted, watch, nextTick } from 'vue'
import {categories,categoryLabel} from '../../shared/categories'
import {request} from '../../shared/api'
import { localDate, taskPayload } from '../../shared/api'
import { dateKey, fromKey, addDays, weekStart, monthDays, eventsOnDay, eventPosition } from '../../shared/calendar'
import { createTask, deleteTask, updateTask } from './api'
const props = defineProps({ tasks: {type:Array,default:()=>[]}, day: String, view: {type:String,default:'week'} })
const emit = defineEmits(['refresh','error','update:day','view-day','select-task'])
const editScope=ref('occurrence')
const deleteChoice=ref(false), deleteScope=ref('occurrence')
const editing=ref(null), busy=ref(false), editorError=ref(''), grid=ref(null), now=ref(new Date())
const days=computed(()=>props.view==='day'?[fromKey(props.day)]:Array.from({length:7},(_,i)=>addDays(weekStart(fromKey(props.day)),i)))
const cells=computed(()=>monthDays(fromKey(props.day)))
const today=computed(()=>dateKey(now.value))
const timer=setInterval(()=>{now.value=new Date()},60000)
onUnmounted(()=>clearInterval(timer))
const time=value=>new Date(value).toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'})
const weekday=d=>d.toLocaleDateString('ru-RU',{weekday:'short'}).replace('.','')
function color(task) { let hash=0; for(const c of task.title) hash+=c.charCodeAt(0); return ['blue','green','purple','orange'][hash%4] }
function edit(task) { emit('select-task',task); editScope.value='occurrence'; editorError.value=''; deleteChoice.value=false; deleteScope.value='occurrence'; editing.value={...task,start:localDate(task.start),end:localDate(task.end),repeat:task.recurrence?.frequency||'none'} }
function add(day=props.day,hour=9) { editorError.value=''; deleteChoice.value=false; editing.value={category:'auto',repeat:'none',title:'',start:`${day}T${String(hour).padStart(2,'0')}:00`,end:localDate(new Date(+fromKey(day)+(hour+1)*3600000))} }
defineExpose({ add })
function slotClick(event,day) {
  if(event.target.closest('.calendar-event')) return
  const bounds=event.currentTarget.getBoundingClientRect()
  const hour=Math.max(0,Math.min(23,Math.floor((event.clientY-bounds.top)/bounds.height*24)))
  add(dateKey(day),hour)
}
async function save() {
  busy.value=true; editorError.value=''
  try { if(editing.value.category==='auto')editing.value.category=(await request('/todos/classify','POST',{title:editing.value.title,description:editing.value.description||''})).category; const data=taskPayload({...editing.value,recurrence:null}); if(editing.value.id) await updateTask(editing.value.id,data,(editing.value.recurrence||editing.value.series_parent_id)?{scope:editScope.value,occurrence_start:editing.value.occurrence_start||editing.value.series_original_start||new Date(editing.value.start).toISOString()}:undefined); else await createTask(data); editing.value=null; emit('refresh') }
  catch(error) { editorError.value=error.message }
  finally {busy.value=false}
}
async function remove() {
  if((editing.value.recurrence||editing.value.series_parent_id) && !deleteChoice.value) { deleteChoice.value=true; return }
  busy.value=true
  try { await deleteTask(editing.value.id,(editing.value.recurrence||editing.value.series_parent_id)?{scope:deleteScope.value,...(deleteScope.value==='occurrence'?{occurrence_start:editing.value.occurrence_start||new Date(editing.value.start).toISOString()}:{} )}:undefined); editing.value=null; emit('refresh') }
  catch(error) { editorError.value=error.message }
  finally {busy.value=false}
}
async function scrollToDay() { await nextTick(); if(grid.value) grid.value.scrollTop=7.5*56 }
onMounted(scrollToDay)
watch(()=>props.view,scrollToDay)
</script>
<template>
  <section class="calendar-workspace" aria-label="Календарь задач">
    <template v-if="view!=='month'">
      <div class="week-heading" :style="{'--days':days.length}"><div class="timezone-label">{{ Intl.DateTimeFormat('ru',{timeZoneName:'shortOffset'}).formatToParts(now).find(p=>p.type==='timeZoneName')?.value }}</div><button v-for="d in days" :key="dateKey(d)" :class="['day-heading',{'is-today':dateKey(d)===today}]" @click="emit('update:day',dateKey(d))"><span>{{ weekday(d) }}</span><b>{{ d.getDate() }}</b></button></div>
      <div class="time-grid-scroll" ref="grid"><div class="time-grid" :style="{'--days':days.length}">
        <div class="hour-labels"><span v-for="hour in 23" :key="hour" :style="{top:hour/24*100+'%'}">{{ String(hour).padStart(2,'0') }}:00</span></div>
        <div v-for="d in days" :key="dateKey(d)" :class="['day-column',{'weekend':d.getDay()===0||d.getDay()===6}]" @click="slotClick($event,d)">
          <div v-for="hour in 24" :key="hour" class="hour-line" :style="{top:(hour-1)/24*100+'%'}"></div>
          <button v-for="task in eventsOnDay(tasks,dateKey(d))" :key="task.occurrence_id||task.id" :data-category="task.category" :class="['calendar-event',color(task)]" :style="eventPosition(task,dateKey(d))" @click.stop="edit(task)" :title="task.title+' · '+categoryLabel(task.category)+' · '+time(task.start)+'–'+time(task.end)"><strong><span v-if="task.is_fixed" aria-label="Нельзя переносить">🔒 </span><span v-if="task.recurrence" aria-label="Повторяющееся событие">↻ </span>{{ task.title }}</strong><span>{{ time(task.start) }} – {{ time(task.end) }}</span></button>
          <div v-if="dateKey(d)===today" class="now-line" :style="{top:(now.getHours()*60+now.getMinutes())/1440*100+'%'}"><i></i></div>
        </div>
      </div></div>
    </template>
    <div v-else class="month-view"><div class="month-weekdays"><span v-for="w in ['Пн','Вт','Ср','Чт','Пт','Сб','Вс']" :key="w">{{ w }}</span></div><div class="month-grid"><div v-for="d in cells" :key="dateKey(d)" :class="['month-cell',{'outside':d.getMonth()!==fromKey(day).getMonth()}]" @dblclick="add(dateKey(d))"><button :class="['month-date',{'today':dateKey(d)===today}]" @click="emit('update:day',dateKey(d));emit('view-day')">{{ d.getDate() }}</button><button v-for="task in eventsOnDay(tasks,dateKey(d))" :key="task.occurrence_id||task.id" :class="['month-event',color(task)]" @click="edit(task)"><i></i><span>{{ time(task.start) }}</span><strong><span v-if="task.is_fixed" aria-label="Нельзя переносить">🔒 </span><span v-if="task.recurrence" aria-label="Повторяющееся событие">↻ </span>{{ task.title }}</strong></button></div></div></div>
  </section>
  <div v-if="editing" class="modal-backdrop" @click.self="!busy && (editing=null)"><section class="event-editor" role="dialog" aria-modal="true" aria-label="Редактор события" @keydown.esc="!busy && (editing=null)"><div class="dialog-heading"><span class="dialog-icon">▤</span><h2>{{ editing.id?'Изменить событие':'Новое событие' }}</h2><button class="icon-button" aria-label="Закрыть редактор" :disabled="busy" @click="editing=null">×</button></div><form @submit.prevent="save"><label>Название<input v-model="editing.title"  required maxlength="200" placeholder="Добавьте название" autofocus></label><label>Описание<textarea v-model="editing.description" maxlength="5000"></textarea></label><label>Категория<select v-model="editing.category"><option v-if="!editing.id" value="auto">Определить с помощью ИИ</option><option v-for="c in categories" :key="c.value" :value="c.value">{{ c.label }}</option></select></label><label class="fixed-event-control"><input v-model="editing.is_fixed" type="checkbox">Нельзя переносить<small>ИИ не будет предлагать перенос. Вручную время можно изменить.</small></label><fieldset v-if="editing.recurrence || editing.series_parent_id"><legend>Применить изменения</legend><label><input v-model="editScope" type="radio" value="occurrence">Только это событие</label><label><input v-model="editScope" type="radio" value="series">Всю серию</label></fieldset><label>Начало<input type="datetime-local" v-model="editing.start"  required></label><label>Окончание<input type="datetime-local" v-model="editing.end"  required></label><label v-if="!editing.id || !editing.recurrence">Повторение<select v-model="editing.repeat"><option value="none">Не повторяется</option><option value="daily">Каждый день · без окончания</option><option value="weekly">Каждую неделю · без окончания</option></select></label><p v-else class="recurrence-description">↻ {{ editing.recurrence.frequency==='weekly'?'Каждую неделю':'Каждый день' }} · без даты окончания. Можно удалить выбранное событие или всю серию.</p><fieldset v-if="deleteChoice" class="delete-series-choice"><legend>Что удалить?</legend><label><input v-model="deleteScope" type="radio" value="occurrence" name="delete-scope">Только это событие</label><label><input v-model="deleteScope" type="radio" value="series" name="delete-scope">Все события серии</label><small>Удаление одного события не затронет остальные повторения.</small></fieldset><p v-if="editorError" class="error-message" role="alert">{{ editorError }}</p><div class="dialog-actions"><button v-if="editing.id" class="danger-button" type="button" :disabled="busy" @click="remove">{{ deleteChoice?'Подтвердить удаление':'Удалить' }}</button><button v-if="deleteChoice" class="outline-button" type="button" :disabled="busy" @click="deleteChoice=false">Отмена</button><button class="primary-button" :disabled="busy">{{ busy?'Сохраняю…':'Сохранить' }}</button></div></form></section></div>
</template>
