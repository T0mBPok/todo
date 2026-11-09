<script setup>
import { computed, ref, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { categoryLabel } from '../../shared/categories'
import { dateKey, fromKey, addDays, weekStart, monthDays, eventsOnDay, positionedEvents } from '../../shared/calendar'
import CalendarEventEditor from './CalendarEventEditor.vue'
const props = defineProps({ tasks: {type:Array,default:()=>[]}, day: String, view: {type:String,default:'week'} })
const emit = defineEmits(['refresh','error','update:day','view-day','select-task'])
const eventEditor = ref(null), grid = ref(null), now = ref(new Date())
const days=computed(()=>props.view==='day'?[fromKey(props.day)]:Array.from({length:7},(_,i)=>addDays(weekStart(fromKey(props.day)),i)))
const timedTasks = computed(() => props.tasks.filter(task => !task.is_all_day))
const allDayTasks = computed(() => props.tasks.filter(task => task.is_all_day))
const allDayColumns = computed(() => days.value.map(day => eventsOnDay(allDayTasks.value, dateKey(day))))
const cells=computed(()=>monthDays(fromKey(props.day)))
const today=computed(()=>dateKey(now.value))
const timer=setInterval(()=>{now.value=new Date()},60000)
onUnmounted(()=>clearInterval(timer))
const time=value=>new Date(value).toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'})
const weekday=d=>d.toLocaleDateString('ru-RU',{weekday:'short'}).replace('.','')
function color(task) { let hash=0; for(const c of task.title) hash+=c.charCodeAt(0); return ['blue','green','purple','orange'][hash%4] }
function preview(task, event) {
  emit('select-task', task)
  eventEditor.value.preview(task, event.currentTarget)
}

function add(day = props.day, hour = 9) {
  eventEditor.value.create(day, hour)
}

defineExpose({ add })
function slotClick(event,day) {
  if(event.target.closest('.calendar-event')) return
  const bounds=event.currentTarget.getBoundingClientRect()
  const hour=Math.max(0,Math.min(23,Math.floor((event.clientY-bounds.top)/bounds.height*24)))
  add(dateKey(day),hour)
}
async function scrollToDay() { await nextTick(); if(grid.value) grid.value.scrollTop=7.5*56 }
onMounted(scrollToDay)
watch(()=>props.view,scrollToDay)
</script>
<template>
  <section class="calendar-workspace" aria-label="Календарь задач">
    <template v-if="view!=='month'">
      <div class="week-heading" :style="{'--days':days.length}"><div class="timezone-label">{{ Intl.DateTimeFormat('ru',{timeZoneName:'shortOffset'}).formatToParts(now).find(p=>p.type==='timeZoneName')?.value }}</div><button v-for="d in days" :key="dateKey(d)" :class="['day-heading',{'is-today':dateKey(d)===today}]" @click="emit('update:day',dateKey(d))"><span>{{ weekday(d) }}</span><b>{{ d.getDate() }}</b></button></div>
      <div v-if="allDayColumns.some(column => column.length)" class="all-day-grid" :style="{'--days':days.length}">
        <span class="all-day-label">Весь день</span>
        <div v-for="(column, index) in allDayColumns" :key="dateKey(days[index])" class="all-day-column">
          <button v-for="task in column" :key="task.id" :class="['month-event',color(task)]" :title="task.title" @click="preview(task, $event)">
            <strong>{{ task.title }}</strong>
          </button>
        </div>
      </div>
      <div class="time-grid-scroll" ref="grid"><div class="time-grid" :style="{'--days':days.length}">
        <div class="hour-labels"><span v-for="hour in 23" :key="hour" :style="{top:hour/24*100+'%'}">{{ String(hour).padStart(2,'0') }}:00</span></div>
        <div v-for="d in days" :key="dateKey(d)" :class="['day-column',{'weekend':d.getDay()===0||d.getDay()===6}]" @click="slotClick($event,d)">
          <div v-for="hour in 24" :key="hour" class="hour-line" :style="{top:(hour-1)/24*100+'%'}"></div>
          <button v-for="{task, style} in positionedEvents(timedTasks,dateKey(d))" :key="task.occurrence_id||task.id" :data-category="task.category" :class="['calendar-event',color(task)]" :style="style" @click.stop="preview(task, $event)" :title="task.title+' · '+categoryLabel(task.category)+' · '+time(task.start)+'–'+time(task.end)"><strong><span v-if="task.is_fixed" aria-label="Нельзя переносить">🔒 </span><span v-if="task.recurrence" aria-label="Повторяющееся событие">↻ </span>{{ task.title }}</strong><span>{{ time(task.start) }} – {{ time(task.end) }}</span></button>
          <div v-if="dateKey(d)===today" class="now-line" :style="{top:(now.getHours()*60+now.getMinutes())/1440*100+'%'}"><i></i></div>
        </div>
      </div></div>
    </template>
    <div v-else class="month-view"><div class="month-weekdays"><span v-for="w in ['Пн','Вт','Ср','Чт','Пт','Сб','Вс']" :key="w">{{ w }}</span></div><div class="month-grid"><div v-for="d in cells" :key="dateKey(d)" :class="['month-cell',{'outside':d.getMonth()!==fromKey(day).getMonth()}]" @dblclick="add(dateKey(d))"><button :class="['month-date',{'today':dateKey(d)===today}]" @click="emit('update:day',dateKey(d));emit('view-day')">{{ d.getDate() }}</button><button v-for="task in eventsOnDay(tasks,dateKey(d))" :key="task.occurrence_id||task.id" :class="['month-event',color(task)]" @click="preview(task, $event)"><i></i><span>{{ task.is_all_day ? 'Весь день' : time(task.start) }}</span><strong><span v-if="task.is_fixed" aria-label="Нельзя переносить">🔒 </span><span v-if="task.recurrence" aria-label="Повторяющееся событие">↻ </span>{{ task.title }}</strong></button></div></div></div>
  </section>
  <CalendarEventEditor ref="eventEditor" @refresh="emit('refresh')" />
</template>

<style scoped>
.all-day-grid {
  display: grid;
  grid-template-columns: 64px repeat(var(--days), minmax(0, 1fr));
  flex-shrink: 0;
  border-bottom: 1px solid var(--line, #dadce0);
  background: #faf5f0;
}
.all-day-label { align-self: center; text-align: center; font-size: .75rem; }
.all-day-column { min-width: 0; padding: 2px 4px; }
@media (max-width: 760px) {
  .all-day-grid { grid-template-columns: 40px repeat(var(--days), minmax(0, 1fr)); }
}
</style>
