<script setup>
const props=defineProps({refreshToken:{type:Number,default:0}})
import { onMounted, ref, computed, watch, nextTick } from 'vue'
import { confirmPlan } from './entities/plans/api'
import { listTasks } from './entities/tasks/api'
import { request, localDate } from './shared/api'
import { dateKey, fromKey, addDays, monthDays, moveDate, visibleRange } from './shared/calendar'
import MicIcon from './features/voice/MicIcon.vue'
import { useVoiceInput } from './features/voice/useVoiceInput'
import PlanEditor from './entities/plans/PlanEditor.vue'
import TaskCalendar from './entities/tasks/TaskCalendar.vue'
import BalanceSuggestions from './features/balance/BalanceSuggestions.vue'
const commandHistory=ref([])
const command=ref(null), choices=ref([]), contextTask=ref(null)
const planEditor = ref(null)
const clearCalendarDraft = ref(null)
const clearScopes = ref({})
const clearReady = computed(() => clearCalendarDraft.value &&
  (clearCalendarDraft.value.series || []).every(item => clearScopes.value[item.series_id]))
const text = ref(''), message = ref(''), plan = ref(null), tasks = ref([]), busy = ref(false), aiReady = ref(null)
const lastTranscript = ref(''), normalizedText = ref(''), savedTasks = ref([])
const autoSave = ref(true), modelName = ref('qwen3.5:4b'), aiProvider=ref(null)
const voiceOpen=ref(false), view=ref('week'), calendar=ref(null), sidebarOpen=ref(window.innerWidth>=760)
const quickMode=ref(false), quickTrigger=ref(null)
const voiceDialog=ref(null), voiceTrigger=ref(null)
watch(voiceOpen,async open=>{ await nextTick(); if(open) voiceDialog.value?.focus(); else (quickMode.value?quickTrigger.value:voiceTrigger.value)?.focus() })
function trapVoiceFocus(event) {
  if(event.key!=='Tab') return
  const nodes=[...voiceDialog.value.querySelectorAll('button:not(:disabled),input:not(:disabled),textarea:not(:disabled),audio,summary')].filter(node=>node.offsetParent!==null)
  const first=nodes[0],last=nodes[nodes.length-1]
  if(event.shiftKey && (document.activeElement===first || document.activeElement===voiceDialog.value)) { event.preventDefault(); last?.focus() }
  else if(!event.shiftKey && document.activeElement===last) { event.preventDefault(); first?.focus() }
}
const day = ref(localDate(new Date()).slice(0,10))
const monthLabel=computed(()=>fromKey(day.value).toLocaleDateString('ru-RU',{month:'long',year:'numeric'}))
const miniDays=computed(()=>monthDays(fromKey(day.value)))
const todayKey=dateKey(new Date())
function navigate(amount) { day.value=moveDate(day.value,amount,view.value) }
function miniMonth(amount) { day.value=moveDate(day.value,amount,'month') }
function closeVoice() { if(!busy.value && !listening.value && !processing.value && !starting.value) voiceOpen.value=false }
const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone
const { supported, listening, processing, starting, toggle, cancel, audioUrl, rawTranscript, engineName, elapsed, recordSeconds } = useVoiceInput({ text, onComplete: () => generate(true), onError: showVoiceError })
function showVoiceError(value) { message.value=value; voiceOpen.value=true }
async function quickMic() {
  if(busy.value || processing.value || starting.value) return
  if(!supported) {showVoiceError('Запись недоступна в этом браузере. Можно ввести текст.');return}
  quickMode.value=true
  if(!listening.value) {text.value='';savedTasks.value=[];message.value=''}
  await toggle()
}
function cancelQuick() { cancel();text.value='';message.value='Запись отменена. Задачи не добавлены.' }
let refreshVersion=0
async function refresh() { const version=++refreshVersion; const result=await listTasks(visibleRange(day.value,view.value)); if(version===refreshVersion) tasks.value=result }
watch([day,view],()=>refreshSafely())
async function refreshSafely() { try { await refresh() } catch (error) { message.value = error.message } }
function readyCommand() {
  return command.value && choices.value.every((c,i)=>c.candidate!==null && (command.value.operations[i].instruction.operation==='create' || !(command.value.operations[i].candidates[c.candidate].recurrence || command.value.operations[i].candidates[c.candidate].series_parent_id) || c.scope))
}
async function executeCommand() {
  if(!readyCommand()) { message.value='Выбери задачу и область изменения.'; return }
  busy.value=true
  try {
    const result=await request(`/commands/${command.value.id}/execute`,'POST',{choices:choices.value})
    message.value=result.note; savedTasks.value=result.tasks; command.value=null; text.value=''
    if(result.tasks.length) {contextTask.value=result.tasks[0];day.value=localDate(result.tasks[0].start).slice(0,10)}
    await refreshSafely()
  } catch(error) { showVoiceError(error.message) }
  finally {busy.value=false;if(quickMode.value && (command.value || plan.value)) voiceOpen.value=true}
}
function cancelCalendarClear() {
  clearCalendarDraft.value = null
  clearScopes.value = {}
  text.value = ''
  message.value = 'Очистка отменена.'
}

function chooseClearScopes(scope) {
  clearScopes.value = Object.fromEntries((clearCalendarDraft.value.series || [])
    .filter(item => scope === 'series' || item.occurrence_start)
    .map(item => [item.series_id, scope]))
}

async function confirmCalendarClear() {
  if (busy.value || !clearReady.value) return
  busy.value = true
  try {
    const choices = (clearCalendarDraft.value.series || []).map(item => ({
      series_id: item.series_id, scope: clearScopes.value[item.series_id]
    }))
    const result = await request(`/commands/${clearCalendarDraft.value.id}/clear-calendar`, 'POST', { choices })
    clearCalendarDraft.value = null
    text.value = ''
    savedTasks.value = []
    contextTask.value = null
    message.value = result.note
    await refreshSafely()
  } catch (error) {
    if (error.status === 409) clearCalendarDraft.value = null
    showVoiceError(error.message)
  } finally {
    busy.value = false
  }
}

async function generate(fromVoice = false) {
  if(busy.value || !text.value.trim()) return
  const utterance=text.value.trim(), lower=utterance.toLowerCase()
  lastTranscript.value=fromVoice?rawTranscript.value:utterance
  if (clearCalendarDraft.value) {
    if (/^(отмена|отмени|не надо)[.! ]*$/.test(lower)) {
      cancelCalendarClear()
      return
    }
    if (/^(?:все|всё) серии целиком[.! ]*$/.test(lower) || /^по одному повторению[.! ]*$/.test(lower)) {
      chooseClearScopes(lower.startsWith('по одному') ? 'occurrence' : 'series')
      text.value = ''
      message.value = clearReady.value ? 'Область удаления выбрана. Подтверди очистку.' : 'Укажи область удаления для оставшихся серий.'
      return
    }
    if (/^подтверждаю очистку календаря[.! ]*$/.test(lower)) {
      if (!clearReady.value) {
        text.value = ''
        message.value = 'Выбери одно повторение или всю серию для каждого события.'
        return
      }
      await confirmCalendarClear()
      return
    }
    if (/^(да|подтверждаю|подтверди|сохрани|выполни)[.! ]*$/.test(lower)) {
      text.value = ''
      message.value = 'Нажми «Подтвердить удаление» или скажи «подтверждаю очистку календаря».'
      voiceOpen.value = true
      return
    }
    clearCalendarDraft.value = null
  }
  if(command.value) {
    if(/^(отмена|отмени|не надо|отменить)[.! ]*$/.test(lower)) {command.value=null;text.value='';message.value='Команда отменена.';return}
    const reply = lower.replace(/[.!? ]+$/, '')
    const scopeReply = reply.replace(/^подтверждаю\s+/, '')
    const ordinal = reply.match(/^(?:(?:выбери|вариант)\s+)?([1-9]|первый|второй|третий|четв[её]ртый|пятый)(?:\s+вариант)?$/)
    const scope = /^(?:всю серию|вся серия|вс[её] повторения|вс[её] события)$/.test(scopeReply)
      ? 'series'
      : /^(?:только )?(?:это событие|одно событие|это повторение|одно повторение)$/.test(scopeReply) ? 'occurrence' : null
    const confirmed = /^(?:подтверждаю|подтверди|выполни|примени|сохрани)$/.test(reply) ||
      (scope && reply.startsWith('подтверждаю '))
    if (ordinal || scope || confirmed) {
      const pending=choices.value.findIndex(c=>c.candidate===null)
      if(ordinal && pending>=0) {
        const selected = ordinal[1]
        const index = /^\d$/.test(selected) ? Number(selected) - 1 : ['перв','втор','трет','четв','пят'].findIndex(word => selected.startsWith(word))
        if(index>=0 && index<command.value.operations[pending].candidates.length) choices.value[pending].candidate=index
      }
      if(scope) choices.value.forEach(c=>c.scope=scope)
      text.value=''
      if(readyCommand() && ((autoSave.value && !command.value.operations.some(o=>o.requires_confirmation)) || confirmed)) await executeCommand();else {message.value='Выбери вариант и область изменения, затем скажи «подтверждаю».';voiceOpen.value=true}
      return
    }
    command.value=null
  }
  if(plan.value && /^(подтверждаю|сохрани|сохранить|добавь в календарь)[.! ]*$/.test(lower)) {
    await planEditor.value?.save()
    return
  }
  if(plan.value && /^(отмена|отмени|не надо)[.! ]*$/.test(lower)) {plan.value=null;text.value='';message.value='План отменён.';return}
  normalizedText.value='';savedTasks.value=[];busy.value=true;plan.value=null;message.value='Разбираю команду…'
  try {
    const range=visibleRange(day.value,view.value)
    const response=await request('/commands','POST',{text:utterance,timezone,context_task_id:contextTask.value?.id||null,context_occurrence_start:contextTask.value?.occurrence_start||null,calendar_start:range.start,calendar_end:range.end,history:commandHistory.value})
    commandHistory.value=[...commandHistory.value,{role:'user',text:utterance.slice(0,1500)},{role:'assistant',text:(response.note||response.plan?.note||'').slice(0,1500)}].slice(-8)
    if (response.kind === 'calendar_clear') {
      clearCalendarDraft.value = response
      clearScopes.value = {}
      text.value = ''
      message.value = ''
      voiceOpen.value = true
    } else if(response.kind==='command') {
      command.value=response
      choices.value=response.operations.map(o=>({candidate:o.candidates.length===1?0:null,scope:o.instruction.scope==='unspecified'?null:o.instruction.scope}))
      text.value='';message.value=response.note
      busy.value=false
      if(autoSave.value && readyCommand() && !response.operations.some(o=>o.requires_confirmation)) await executeCommand()
    } else {
      const result=response.plan;plan.value=result;normalizedText.value=result.normalized_text||''
      if(autoSave.value && result.tasks.length === 1 && !result.review?.length) {savedTasks.value=await confirmPlan(result.id,result.tasks);contextTask.value=savedTasks.value.length===1?savedTasks.value[0]:null;await saved(localDate(result.tasks[0].start).slice(0,10))}
      else {text.value='';message.value='Проверь предложенные события перед сохранением.';voiceOpen.value=true}
    }
  } catch(error) {commandHistory.value=[...commandHistory.value,{role:'user',text:utterance.slice(0,1500)},{role:'assistant',text:(error.detail||error.message).slice(0,1500)}].slice(-8);showVoiceError(error.message)}
  finally {busy.value=false;if(quickMode.value && (command.value || plan.value)) voiceOpen.value=true}
}
function submitText() { cancel(); generate(false) }
function mic() { quickMode.value=false; if (!listening.value) message.value = 'Говори, затем нажми «Завершить запись».'; toggle() }
function retryTranscript() { text.value = rawTranscript.value || lastTranscript.value; message.value = 'Исправь текст и отправь снова. Уже добавленные задачи можно изменить в календаре.' }
const displayTime = value => new Date(value).toLocaleString('ru-RU', { weekday:'short', day:'numeric', month:'short', hour:'2-digit', minute:'2-digit' })
async function saved(date, note = plan.value?.note) {
  day.value = date; plan.value = null; text.value = ''; message.value = quickMode.value ? `Добавлено в календарь: ${savedTasks.value.length || 1}.` : 'Задачи добавлены в календарь.' + (note ? ' ' + note : '')
  await refreshSafely()
}
async function savedFromPreview(date, events) {
  savedTasks.value = events
  contextTask.value = events.length === 1 ? events[0] : null
  await saved(date)
}

onMounted(async () => {
  await refreshSafely()
  try { const state = await request('/health'); aiReady.value = state.ai_configured; modelName.value = state.ai_model; aiProvider.value = state.ai_provider }
  catch (error) { message.value = error.message }
})
watch(()=>props.refreshToken,()=>refreshSafely())
</script>
<template>
  <div class="calendar-app">
    <header class="app-toolbar">
      <button class="icon-button menu-button" aria-label="Показать или скрыть боковую панель" @click="sidebarOpen=!sidebarOpen">☰</button>
      <div class="calendar-section-label">ПЛАН / 01</div>
      <button class="outline-button today-button" @click="day=todayKey">Сегодня</button>
      <div class="navigation-arrows"><button class="icon-button" aria-label="Предыдущий период" @click="navigate(-1)">‹</button><button class="icon-button" aria-label="Следующий период" @click="navigate(1)">›</button></div>
      <h1 class="period-title">{{ monthLabel }}</h1>
      <div class="toolbar-spacer"></div>
      <button ref="quickTrigger" :class="['quick-record-button',{'is-recording':listening}]" :aria-label="listening?'Завершить быструю запись':'Начать быструю запись'" :title="listening?'Остановить запись':'Записать голосом, не закрывая календарь'" :disabled="busy||processing||starting" @click="quickMic"><span v-if="listening" class="quick-stop-symbol">■</span><MicIcon v-else /><span>{{ listening?'Стоп':processing?'Распознаю…':starting?'Микрофон…':busy?'Обрабатываю…':'Говорить' }}</span></button>
      <button ref="voiceTrigger" class="voice-toolbar-button" aria-label="Открыть голосовую запись" @click="voiceOpen=true"><MicIcon /><span>Панель голоса</span></button>
      <select v-model="view" class="view-select" aria-label="Вид календаря"><option value="day">День</option><option value="week">Неделя</option><option value="month">Месяц</option></select>
      
    </header>
    <div :class="['app-content',{'sidebar-collapsed':!sidebarOpen}]">
      <aside v-if="sidebarOpen" class="calendar-sidebar">
        <p class="sidebar-kicker">РАБОЧАЯ ОБЛАСТЬ</p><button class="create-button" @click="calendar?.add()"><span>＋</span>Создать</button>
        <section class="mini-calendar"><div class="mini-heading"><b>{{ monthLabel }}</b><div><button class="icon-button" aria-label="Предыдущий месяц" @click="miniMonth(-1)">‹</button><button class="icon-button" aria-label="Следующий месяц" @click="miniMonth(1)">›</button></div></div><div class="mini-weekdays"><span v-for="(w,i) in ['П','В','С','Ч','П','С','В']" :key="i">{{ w }}</span></div><div class="mini-days"><button v-for="d in miniDays" :key="dateKey(d)" :class="{'muted':d.getMonth()!==fromKey(day).getMonth(),'selected':dateKey(d)===day,'today':dateKey(d)===todayKey}" @click="day=dateKey(d)">{{ d.getDate() }}</button></div></section>
        <div class="sidebar-section"><h2>Мои календари <span>⌃</span></h2><div class="calendar-label"><span class="calendar-checkbox">✓</span>Мои задачи</div></div>
        <div class="voice-sidebar-card"><div class="voice-small-icon"><MicIcon /></div><h3>Голосовая заметка</h3><p>Расскажи о делах.<br>Они появятся в календаре.</p><button @click="voiceOpen=true">Сделать запись <span>→</span></button></div>

        <div v-if="aiProvider" class="impulse-provider" :title="modelName"><i aria-hidden="true"></i>{{ aiProvider==='dashscope'?'Qwen · Alibaba Cloud':aiProvider==='openrouter'?'ИИ · OpenRouter':aiProvider==='gigachat'?'ИИ · GigaChat':'Qwen · локальный' }}</div>
      </aside>
      <div class="calendar-with-suggestions"><TaskCalendar ref="calendar" :tasks="tasks" v-model:day="day" :view="view" @select-task="contextTask=$event" @view-day="view='day'" @refresh="refreshSafely" @error="message=$event;voiceOpen=true" /><BalanceSuggestions :tasks="tasks" @applied="message=$event;refreshSafely()" /></div>
    </div>
    <div v-if="message && !voiceOpen && !listening && !processing && !starting && !busy" class="calendar-toast" role="status"><span>{{ message }}</span><button aria-label="Закрыть сообщение" @click="message=''">×</button></div>
    <div v-if="!voiceOpen && (listening||starting||processing||busy)" class="quick-voice-bar" role="status" aria-live="polite"><span :class="['quick-status-dot',{'recording':listening}]"></span><div><strong>{{ listening?'Идёт запись · '+recordSeconds+' с':starting?'Подключаю микрофон…':processing?'Распознаю речь…':'Обрабатываю команду…' }}</strong><small>{{ listening?'Календарь перед глазами. Нажми «Стоп», когда закончишь.':'Можно продолжать смотреть календарь' }}</small></div><button v-if="listening" class="quick-finish" @click="quickMic">Стоп</button><button v-if="listening||starting" class="icon-button" aria-label="Отменить быструю запись" @click="cancelQuick">×</button><button class="quick-details" @click="voiceOpen=true">Панель</button></div>
    <div v-show="voiceOpen" class="voice-backdrop" @click.self="closeVoice"><section ref="voiceDialog" tabindex="-1" class="voice-window" role="dialog" @keydown="trapVoiceFocus" aria-modal="true" aria-labelledby="voice-title" @keydown.esc="closeVoice">
      <div class="voice-window-heading"><div class="voice-title-icon"><MicIcon /></div><div><h2 id="voice-title">Управление голосом</h2><p>Добавляй, изменяй и удаляй задачи</p></div><button class="icon-button" aria-label="Закрыть голосовое окно" :disabled="busy||listening||processing||starting" @click="closeVoice">×</button></div>
      <div class="voice-window-body">
        <div v-if="aiReady===false" class="notice">ИИ не настроен или недоступен. Проверь настройки выбранного провайдера.</div>
        <button :class="['record-main-button',{'recording':listening}]" :disabled="!supported||busy||processing||starting" @click="mic"><span class="mic-symbol"><template v-if="listening">■</template><MicIcon v-else /></span><b>{{ processing?'Распознаю речь…':starting?'Подключаю микрофон…':listening?'Завершить запись':'Нажми и говори' }}</b><small>{{ listening?recordSeconds+' с · до 90 секунд':'Например: «Каждый вторник в 18:00 тренировка»' }}</small></button>
        <button v-if="listening||starting||processing" class="cancel-record-button panel-cancel-record" @click="cancelQuick">× Отменить запись</button>
        <form @submit.prevent="submitText"><label>Что нужно сделать?<textarea v-model="text" :disabled="busy||listening||processing||starting" required maxlength="6000" placeholder="Можно продиктовать или написать здесь…"></textarea></label><label class="auto-save"><input v-model="autoSave" type="checkbox" :disabled="busy||listening||processing||starting">Автоматически выполнять однозначные команды</label><button class="primary-button voice-submit" :disabled="busy||listening||processing||starting||!text.trim()">{{ busy?'Составляю расписание…':autoSave?'Выполнить команду':'Показать результат' }}</button></form>
        <p v-if="!supported" class="notice">Запись недоступна в этом браузере. Можно ввести текст.</p>
        <p v-if="message||processing" class="voice-status" role="status" aria-live="polite">{{ processing?'Распознаю запись локально…':message }}</p>
        <section v-if="clearCalendarDraft" class="preview calendar-clear-review" aria-labelledby="calendar-clear-title">
          <h3 id="calendar-clear-title">{{ clearCalendarDraft.note }}</h3>
          <p>Разовых событий к удалению: {{ clearCalendarDraft.ordinary }}.</p>
          <div v-if="clearCalendarDraft.series?.length > 1">
            <button type="button" class="link" :disabled="busy" @click="chooseClearScopes('occurrence')">По одному повторению</button>
            <button type="button" class="link" :disabled="busy" @click="chooseClearScopes('series')">Все серии целиком</button>
          </div>
          <fieldset v-for="item in clearCalendarDraft.series" :key="item.series_id" :disabled="busy">
            <legend>{{ item.title }}</legend>
            <label v-if="item.occurrence_start">
              <input type="radio" :name="'clear-' + item.series_id" v-model="clearScopes[item.series_id]" value="occurrence">
              Только {{ displayTime(item.occurrence_start) }}
            </label>
            <label>
              <input type="radio" :name="'clear-' + item.series_id" v-model="clearScopes[item.series_id]" value="series">
              Вся серия
            </label>
          </fieldset>
          <p>Можно сказать «подтверждаю очистку календаря».</p>
          <div>
            <button type="button" class="outline-button" :disabled="busy" @click="cancelCalendarClear">Отмена</button>
            <button type="button" class="calendar-clear-button" :disabled="busy || !clearReady" @click="confirmCalendarClear">Подтвердить удаление</button>
          </div>
        </section>
        <section v-if="audioUrl||lastTranscript" class="speech-result"><div class="result-heading"><h3>{{ audioUrl?'Твоя запись':'Исходный текст' }}</h3><span v-if="engineName" class="engine-badge">{{ engineName }}<template v-if="elapsed"> · {{ elapsed }} с</template></span></div><audio v-if="audioUrl" :src="audioUrl" controls preload="metadata" aria-label="Прослушать последнюю запись"></audio><details v-if="lastTranscript"><summary>Расшифровка и исправления</summary><h4>Распознано из аудио</h4><p>{{ rawTranscript||lastTranscript }}</p><template v-if="normalizedText"><h4>Как разобрана команда</h4><p>{{ normalizedText }}</p></template><button class="link" :disabled="busy" @click="retryTranscript">Исправить текст</button></details></section>
        <section v-if="savedTasks.length" class="saved-results"><h3>Результат: {{ savedTasks.length }}</h3><article v-for="task in savedTasks" :key="task.id" class="saved-event"><span class="saved-check">✓</span><div><strong>{{ task.title }}<span v-if="task.recurrence" class="repeat-badge"> ↻ {{ task.recurrence.frequency==='weekly'?'Каждую неделю':'Каждый день' }}</span></strong><small>{{ displayTime(task.start) }} — {{ displayTime(task.end) }}</small><p v-if="task.description">{{ task.description }}</p></div></article><button class="outline-button" @click="closeVoice">Посмотреть в календаре</button></section>
        <section v-if="command" class="preview command-review"><h3>Подтверждение команды</h3><p>{{ command.note }}</p><p>Можно сказать «первый вариант», «только это событие», «всю серию», «подтверждаю» или «отмена».</p><article v-for="(op,i) in command.operations" :key="i" class="draft"><h4>{{ op.instruction.operation==='create'?'Добавить':op.instruction.operation==='delete'?'Удалить':'Изменить' }}: {{ op.instruction.target || 'Выбранная задача' }}</h4><label v-for="(candidate,n) in op.candidates" :key="candidate.occurrence_id||candidate.id"><input type="radio" :name="'candidate-'+i" v-model="choices[i].candidate" :value="n">{{ n+1 }}. {{ candidate.title }} · {{ displayTime(candidate.start) }}</label><p v-if="op.instruction.new_recurrence">Повторение: {{ op.instruction.new_recurrence==='weekly'?'каждую неделю':'каждый день' }} · без окончания. Дата, время и описание сохраняются.</p><p v-if="op.instruction.new_title">Название: {{ op.instruction.new_title }}</p><p v-if="op.instruction.new_time || op.instruction.new_date_reference">Новое время: {{ op.instruction.new_date_reference }} {{ op.instruction.new_time }}</p><p v-if="op.instruction.description!==null">{{ op.instruction.append_description?'Добавить в описание':'Описание' }}: {{ op.instruction.description }}</p><fieldset v-if="op.instruction.operation!=='create' && choices[i].candidate!==null && (op.candidates[choices[i].candidate].recurrence || op.candidates[choices[i].candidate].series_parent_id)"><legend>Какие повторения?</legend><label><input type="radio" v-model="choices[i].scope" value="occurrence">Только это событие</label><label><input type="radio" v-model="choices[i].scope" value="series">Вся серия</label></fieldset></article><button class="primary-button" :disabled="busy || !readyCommand()" @click="executeCommand">Подтвердить</button><button class="outline-button" :disabled="busy" @click="command=null;text='';message='Команда отменена.'">Отмена</button></section>
        <PlanEditor v-if="plan&&!busy" ref="planEditor" :key="plan.id" :plan="plan" @saved="savedFromPreview" @error="message=$event" />
      </div><div class="voice-window-footer"><span class="local-dot"></span>Локальное распознавание · без облачных сервисов</div>
    </section></div>
  </div>
</template>

<style scoped>
.calendar-clear-review { margin: 12px 0 16px; padding: 12px; border: 1px solid #e9c9bd; border-radius: 8px; background: #fff6f1; }
.calendar-clear-review p { margin: 5px 0 10px; color: var(--muted); font-size: 12px; }
.calendar-clear-review > div { display: flex; justify-content: flex-end; flex-wrap: wrap; gap: 8px; }
.calendar-clear-review fieldset { margin: 10px 0; padding: 4px 10px 7px; min-width: 0; border: 1px solid #e9c9bd; border-radius: 7px; }
.calendar-clear-review fieldset label { display: flex; align-items: center; gap: 8px; margin: 6px 0 0; font-weight: 400; }
.calendar-clear-review fieldset input { width: auto; margin: 0; }
.calendar-clear-button { padding: 8px 12px; border-radius: 7px; background: #a03226; color: white; font-weight: 600; }
</style>
