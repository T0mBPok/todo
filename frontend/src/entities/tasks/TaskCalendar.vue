<script setup>
import { computed, ref, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { dateKey, fromKey, addDays, monthDays, eventsOnDay, positionedEvents } from '../../shared/calendar'
import { createCalendarWindow, calendarWindowRange, calendarScrollPosition, shiftCalendarDate } from '../../shared/calendarScroll'
import TodoCalendarItem from '../todos/TodoCalendarItem.vue'
import TodoEditor from '../todos/TodoEditor.vue'
import TodoDetails from '../todos/TodoDetails.vue'
import {request} from '../../shared/api.js'
import {errorMessage} from '../../shared/errors.js'
import CalendarEventEditor from './CalendarEventEditor.vue'
import CalendarEventCard from './CalendarEventCard.vue'
const props = defineProps({ tasks: {type:Array,default:()=>[]}, day: String, view: {type:String,default:'week'} })
const emit = defineEmits(['range-change','refresh','error','update:day','view-day','select-task'])
const todoDetails=ref(null), todoEditor=ref(null), completing=ref(new Set())
const eventEditor = ref(null), grid = ref(null), timeGrid = ref(null), eventHeaders = ref({}), now = ref(new Date())
const viewportWidth = ref(800), gutterWidth = ref(64), horizontalPosition = ref(0)
const windowState = ref(createCalendarWindow(props.day, props.view))
const unitWidth = computed(() => props.view === 'month' ? viewportWidth.value :
  (viewportWidth.value - gutterWidth.value) / windowState.value.visible)
const timelineStyle = computed(() => ({
  '--days': windowState.value.length, '--column-width': unitWidth.value + 'px',
  '--gutter-width': gutterWidth.value + 'px', '--viewport-width': viewportWidth.value + 'px',
  width: (props.view === 'month' ? unitWidth.value * windowState.value.length :
    gutterWidth.value + unitWidth.value * windowState.value.length) + 'px'
}))
const days = computed(() => Array.from({length:windowState.value.length},
  (_, i) => addDays(windowState.value.start, i)))
const months = computed(() => Array.from({length:windowState.value.length}, (_, i) => {
  const month = shiftCalendarDate(windowState.value.start, i, 'month')
  return { key: dateKey(month), month, cells: monthDays(month) }
}))
function eventHeaderKey(day,task) { return day+':'+(task.occurrence_id||task.id) }
function measureHeader(day,task,height) {
  const key=eventHeaderKey(day,task)
  if(eventHeaders.value[key]!==height)eventHeaders.value={...eventHeaders.value,[key]:height}
}
function dayEvents(day) {
  return positionedEvents(timedTasks.value,day,{
    pixelsPerMinute:timeGrid.value?.offsetHeight/1440 || 64/60,
    headerHeight:task=>eventHeaders.value[eventHeaderKey(day,task)] || 64
  })
}
const timedTasks = computed(() => props.tasks.filter(task => !task.is_all_day))
const allDayTasks = computed(() => props.tasks.filter(task => task.is_all_day))
const allDayColumns = computed(() => days.value.map(day => eventsOnDay(allDayTasks.value, dateKey(day))))
const showAllDay = computed(() => {
  const offset = horizontalPosition.value / Math.max(1,unitWidth.value)
  const first = Math.floor(offset + 0.00001)
  const last = Math.ceil(offset + windowState.value.visible - 0.00001)
  return allDayColumns.value.slice(first,last).some(column => column.length)
})
const today=computed(()=>dateKey(now.value))
const timer=setInterval(()=>{now.value=new Date()},60000)
onUnmounted(() => { clearInterval(timer); resizeObserver?.disconnect() })
const time=value=>new Date(value).toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'})
const weekday=d=>d.toLocaleDateString('ru-RU',{weekday:'short'}).replace('.','')
function color(task) { let hash=0; for(const c of task.title) hash+=c.charCodeAt(0); return ['blue','green','purple','orange'][hash%4] }
function preview(task, event) {
  if (Date.now() < suppressClickUntil) return
  if(task.entity==='todo'){previewTodo(task);return}
  emit('select-task', task)
  eventEditor.value.preview(task, event.currentTarget)
}

function previewTodo(task) {
  if (window.matchMedia('(max-width:760px)').matches) todoDetails.value.open(task)
  else todoEditor.value.open(task)
}

async function completeTodo(task) {
  if(completing.value.has(task.todo_id))return
  completing.value.add(task.todo_id)
  try{await request('/todos/'+task.todo_id+'/completion','PATCH',{completed:!task.completed});emit('refresh')}
  catch(e){emit('error',errorMessage(e))}finally{completing.value.delete(task.todo_id)}
}
let suppressClickUntil = 0
let pointerStart = null
let emittedDay = null
let resetting = false
let resizeObserver
let pendingReset = 0
let lastScrollLeft = null

function startDrag(event) { pointerStart = { x:event.clientX, y:event.clientY } }
function moveDrag(event) {
  if (pointerStart && Math.hypot(event.clientX-pointerStart.x, event.clientY-pointerStart.y) > 6)
    suppressClickUntil = Date.now() + 400
}
function horizontalWheel(event) {
  if (!event.shiftKey || event.ctrlKey || !grid.value) return
  const delta = event.deltaY || event.deltaX
  if (!delta) return
  event.preventDefault()
  grid.value.scrollLeft += delta * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? viewportWidth.value : 1)
}
function publishRange() { emit('range-change', calendarWindowRange(windowState.value)) }
function getVisibleRange() {
  const state = windowState.value
  if (!grid.value) return calendarWindowRange(createCalendarWindow(props.day, props.view))
  const { index, unit } = calendarScrollPosition(state, grid.value.scrollLeft, viewportWidth.value, gutterWidth.value)
  if (props.view === 'month') {
    const first = shiftCalendarDate(state.start, index, 'month')
    const last = shiftCalendarDate(first, grid.value.scrollLeft - index * unit > 0.5 ? 1 : 0, 'month')
    return { start:monthDays(first)[0].toISOString(), end:addDays(monthDays(last)[41],1).toISOString() }
  }
  const first = addDays(state.start, index)
  const columns = Math.ceil((grid.value.scrollLeft - index * unit + viewportWidth.value - gutterWidth.value) / unit - 0.00001)
  return { start:first.toISOString(), end:addDays(first,columns).toISOString() }
}
async function onScroll() {
  if (resetting || !grid.value) return
  suppressClickUntil = Date.now() + 250
  const currentLeft = grid.value.scrollLeft
  horizontalPosition.value = currentLeft
  if (lastScrollLeft !== null && Math.abs(currentLeft-lastScrollLeft) < 0.5) return
  lastScrollLeft = currentLeft
  const position = calendarScrollPosition(windowState.value, currentLeft, viewportWidth.value, gutterWidth.value)
  if (position.day !== props.day) {
    emittedDay = position.day
    emit('update:day', position.day)
  }
  if (!position.shift) return
  resetting = true
  const left = grid.value.scrollLeft
  const version = pendingReset
  windowState.value = { ...windowState.value,
    start:shiftCalendarDate(windowState.value.start, position.shift, props.view) }
  await nextTick()
  if (!grid.value || version !== pendingReset) return
  grid.value.scrollLeft = left - position.shift * position.unit
  lastScrollLeft = grid.value.scrollLeft
  horizontalPosition.value = grid.value.scrollLeft
  publishRange()
  resetting = false
}
async function resetWindow(resetTime = false) {
  const version = ++pendingReset
  resetting = true
  windowState.value = createCalendarWindow(props.day, props.view)
  await nextTick()
  if (!grid.value || version !== pendingReset) return
  viewportWidth.value = grid.value.clientWidth
  gutterWidth.value = window.innerWidth <= 760 ? 40 : 64
  await nextTick()
  if (!grid.value || version !== pendingReset) return
  grid.value.scrollLeft = windowState.value.padding * unitWidth.value
  lastScrollLeft = grid.value.scrollLeft
  horizontalPosition.value = grid.value.scrollLeft
  if (resetTime) grid.value.scrollTop = props.view === 'month' ? 0 : 7.5 * 64
  publishRange()
  resetting = false
}
onMounted(async () => {
  await resetWindow(true)
  resizeObserver = new ResizeObserver(() => {
    if (!grid.value || grid.value.clientWidth === viewportWidth.value) return
    if (resetting) return
    const version = pendingReset
    const oldUnit = unitWidth.value
    const offset = grid.value.scrollLeft / oldUnit
    viewportWidth.value = grid.value.clientWidth
    gutterWidth.value = window.innerWidth <= 760 ? 40 : 64
    nextTick(() => {
      if (!grid.value || resetting || version !== pendingReset) return
      grid.value.scrollLeft = offset * unitWidth.value
      lastScrollLeft = grid.value.scrollLeft
  horizontalPosition.value = grid.value.scrollLeft
    })
  })
  resizeObserver.observe(grid.value)
})
watch(() => props.day, value => {
  if (value === emittedDay) { emittedDay = null; return }
  resetWindow()
})
watch(() => props.view, () => { emittedDay = null; resetWindow(true) })

function add(day = props.day, hour = 9) {
  eventEditor.value.create(day, hour)
}

function savedTodo(todo) {
  if(todo?.scheduled_date)emit('update:day',todo.scheduled_at?dateKey(new Date(todo.scheduled_at)):todo.scheduled_date)
  emit('refresh')
}
function addTodo() {todoEditor.value.create(props.day)}
defineExpose({ add, addTodo, getVisibleRange })
function slotClick(event,day) {
  if(Date.now() < suppressClickUntil || event.target.closest('.calendar-event')) return
  const bounds=event.currentTarget.getBoundingClientRect()
  const hour=Math.max(0,Math.min(23,Math.floor((event.clientY-bounds.top)/bounds.height*24)))
  add(dateKey(day),hour)
}
</script>
<template>
  <section class="calendar-workspace" :class="'calendar-view-' + view" aria-label="Календарь задач">
    <div ref="grid" class="continuous-calendar-scroll" tabindex="0" aria-label="Прокрутка календаря" :class="{'is-month':view==='month'}"
      @scroll.passive="onScroll" @wheel="horizontalWheel" @pointerdown.passive="startDrag"
      @pointermove.passive="moveDrag" @pointerup="pointerStart=null" @pointercancel="pointerStart=null">
    <div v-if="view!=='month'" class="calendar-timeline" :style="timelineStyle">
      <div class="week-heading"><div class="timezone-label">{{ Intl.DateTimeFormat('ru',{timeZoneName:'shortOffset'}).formatToParts(now).find(p=>p.type==='timeZoneName')?.value }}</div><button v-for="d in days" :key="dateKey(d)" :class="['day-heading',{'is-today':dateKey(d)===today}]" @click="emit('update:day',dateKey(d))"><span>{{ weekday(d) }}</span><b>{{ d.getDate() }}</b></button></div>
      <div v-if="showAllDay" class="all-day-grid">
        <span class="all-day-label">Весь день</span>
        <div v-for="(column, index) in allDayColumns" :key="dateKey(days[index])" class="all-day-column">
          <template v-for="task in column" :key="task.id"><TodoCalendarItem v-if="task.entity==='todo'" :task="task" compact @open="previewTodo" @complete="completeTodo"/><button v-else :class="['month-event',color(task)]" :title="task.title" @click="preview(task,$event)"><strong>{{ task.title }}</strong></button></template>
        </div>
      </div>
      <div ref="timeGrid" class="time-grid">
        <div class="hour-labels"><span v-for="hour in 23" :key="hour" :style="{top:hour/24*100+'%'}">{{ String(hour).padStart(2,'0') }}:00</span></div>
        <div v-for="d in days" :key="dateKey(d)" :class="['day-column',{'weekend':d.getDay()===0||d.getDay()===6}]" @click="slotClick($event,d)">
          <div v-for="hour in 24" :key="hour" class="hour-line" :style="{top:(hour-1)/24*100+'%'}"></div>
          <template v-for="{task,style} in dayEvents(dateKey(d))" :key="task.occurrence_id||task.id"><TodoCalendarItem v-if="task.entity==='todo'" class="calendar-event calendar-todo-position" :task="task" :style="style" @open="previewTodo" @complete="completeTodo"/>          <CalendarEventCard v-else :task="task" :data-category="task.category" :class="color(task)" :style="style" @open="preview(task,$event)" @header-size="measureHeader(dateKey(d),task,$event)"/></template>
          <div v-if="dateKey(d)===today" class="now-line" :style="{top:(now.getHours()*60+now.getMinutes())/1440*100+'%'}"><i></i></div>
        </div>
      </div>
    </div>
    <div v-else class="calendar-month-track" :style="timelineStyle">
      <div v-for="panel in months" :key="panel.key" class="month-view calendar-month-panel">
        <div class="month-panel-title">{{ panel.month.toLocaleDateString('ru-RU',{month:'long',year:'numeric'}) }}</div>
        <div class="month-weekdays"><span v-for="w in ['Пн','Вт','Ср','Чт','Пт','Сб','Вс']" :key="w">{{ w }}</span></div>
        <div class="month-grid"><div v-for="d in panel.cells" :key="dateKey(d)" :class="['month-cell',{'outside':d.getMonth()!==panel.month.getMonth()}]" @dblclick="add(dateKey(d))">
          <button :class="['month-date',{'today':dateKey(d)===today}]" @click="emit('update:day',dateKey(d));emit('view-day')">{{ d.getDate() }}</button>
          <template v-for="task in eventsOnDay(tasks,dateKey(d))" :key="task.occurrence_id||task.id"><TodoCalendarItem v-if="task.entity==='todo'" :task="task" compact @open="previewTodo" @complete="completeTodo"/>          <button v-else :class="['month-event',color(task)]" @click="preview(task, $event)"><i></i><span class="calendar-event-time">{{ task.is_all_day ? 'Весь день' : time(task.start) }}</span><strong><span v-if="task.is_fixed" aria-label="Нельзя переносить">🔒 </span>{{ task.title }}</strong></button></template>
        </div></div>
      </div>
    </div>
    </div>
  </section>
  <TodoDetails ref="todoDetails" @saved="savedTodo" @edit="todoEditor.open($event)"/>
  <TodoEditor ref="todoEditor" @saved="savedTodo"/>
  <CalendarEventEditor ref="eventEditor" @refresh="emit('refresh')" />
</template>

<style scoped>
.month-event strong{font-size:12px;line-height:1.25}

.calendar-todo-position{min-height:32px;padding:5px 7px;text-align:left;}
.continuous-calendar-scroll { flex:1; min-height:0; overflow:auto; overscroll-behavior-x:contain; touch-action:auto; overflow-anchor:none; }
.calendar-timeline { position:relative; }
.day-column { isolation:isolate; }
.day-column :deep(.calendar-event) { z-index:var(--event-stack,2); }
.calendar-timeline .week-heading,.calendar-timeline .time-grid,.calendar-timeline .all-day-grid {
  display:grid; grid-template-columns:var(--gutter-width) repeat(var(--days),var(--column-width));
}
.calendar-timeline .week-heading { position:sticky; top:0; z-index:10; padding-top:0; }
.calendar-timeline .timezone-label { align-self:stretch; display:flex; align-items:flex-end; justify-content:center; }
.calendar-timeline .timezone-label,.calendar-timeline .hour-labels,.all-day-label { position:sticky; left:0; z-index:6; background:var(--paper,#fffcf8); }
.calendar-timeline .timezone-label { z-index:11; }
.calendar-timeline .day-heading { min-width:0; }
.calendar-timeline .hour-labels { z-index:5; }
.all-day-grid { position:sticky; top:var(--calendar-days-height,52px); z-index:9; border-bottom:1px solid var(--line); background:var(--paper); }
.all-day-label { display:grid; place-items:center; font-size:10px; }
.all-day-column { min-width:0; padding:2px 4px; }
.calendar-month-track { display:flex; height:100%; }
.calendar-month-panel { flex:0 0 var(--viewport-width); width:var(--viewport-width); border-right:1px solid var(--line); }
.month-panel-title { flex-shrink:0; text-align:center; padding:10px; text-transform:capitalize; font-size:12px; color:var(--muted); }
.calendar-month-panel .month-grid { overflow:visible; min-height:0; grid-template-rows:repeat(6,minmax(0,1fr)); }
.calendar-month-panel .month-cell { overflow:auto; }
@media(max-width:760px) {
  .continuous-calendar-scroll,.calendar-month-panel .month-cell { scrollbar-width:none!important; }
  .continuous-calendar-scroll::-webkit-scrollbar,.calendar-month-panel .month-cell::-webkit-scrollbar { display:none; width:0; height:0; }
  .calendar-timeline .timezone-label,.calendar-timeline .hour-labels,.all-day-label { background:#f0eae4; }
  .calendar-timeline .hour-labels>span { left:0; right:0; text-align:center; }
  .all-day-label { text-align:center; padding:2px; line-height:1.15; }
  .all-day-column { padding:1px 2px; }
  .month-event .calendar-event-time { display:none; }
}
</style>
