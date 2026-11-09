<script setup>
import { nextTick, ref } from 'vue'
import { categories, categoryLabel } from '../../shared/categories'
import { localDate, request, taskPayload } from '../../shared/api'
import { fromKey } from '../../shared/calendar'
import { createTask, deleteTask, updateTask } from './api'

const emit = defineEmits(['refresh'])
const details = ref(null), editor = ref(null), scopeDialog = ref(null)
const selected = ref(null), draft = ref(null)
const busy = ref(false), error = ref('')
const scopeAction = ref(''), scope = ref('occurrence')
const position = ref({ left: '12px', top: '12px' })
const dayMs = 24 * 60 * 60 * 1000
const fullDate = new Intl.DateTimeFormat('ru-RU', { weekday: 'long', day: 'numeric', month: 'long' })
const floatingDate = new Intl.DateTimeFormat('ru-RU', { weekday: 'long', day: 'numeric', month: 'long', timeZone: 'UTC' })
const clock = new Intl.DateTimeFormat('ru-RU', { hour: '2-digit', minute: '2-digit' })
const isSeries = task => Boolean(task?.recurrence || task?.series_parent_id)

function period(task) {
  const start = new Date(task.start), end = new Date(task.end)
  if (task.is_all_day) {
    const first = floatingDate.format(start)
    const last = floatingDate.format(new Date(+end - dayMs))
    return (first === last ? first : first + ' — ' + last) + ' · Весь день'
  }
  const first = fullDate.format(start), last = fullDate.format(end)
  return first === last ? first + ' · ' + clock.format(start) + '–' + clock.format(end)
    : first + ', ' + clock.format(start) + ' — ' + last + ', ' + clock.format(end)
}

function repeatLabel(task) {
  if (task.recurrence?.frequency === 'daily') return 'Каждый день'
  if (task.recurrence?.frequency === 'weekly') return 'Каждую неделю'
  if (task.recurrence?.frequency === 'google') return 'Повторение по правилу Google'
  return 'Повторяющееся событие'
}

function calendarInput(value, allDay, end = false) {
  if (!allDay) return localDate(value)
  return new Date(+new Date(value) - (end ? dayMs : 0)).toISOString().slice(0, 10)
}

function inputValue(day, time, original, allDay, end = false) {
  const value = allDay ? day : day + 'T' + time
  if (original && value === calendarInput(original, allDay, end)) return original
  return allDay && end ? new Date(+new Date(day) + dayMs).toISOString() : value
}

async function preview(task, anchor) {
  const box = anchor.getBoundingClientRect()
  selected.value = task
  error.value = ''
  await nextTick()
  details.value.showModal()
  const width = details.value.offsetWidth, height = details.value.offsetHeight, gap = 12
  let left = box.right + gap
  if (left + width > window.innerWidth - gap) left = box.left - width - gap
  if (left < gap) left = Math.min(box.left, window.innerWidth - width - gap)
  position.value = {
    left: Math.max(gap, left) + 'px',
    top: Math.max(gap, Math.min(box.top, window.innerHeight - height - gap)) + 'px'
  }
}

function closeDetails() {
  if (busy.value) return
  details.value.close()
  selected.value = null
  error.value = ''
}

async function showEditor(task) {
  const start = calendarInput(task.start, task.is_all_day)
  const end = calendarInput(task.end, task.is_all_day, true)
  draft.value = {
    ...task, startDate: start.slice(0, 10), endDate: end.slice(0, 10),
    startTime: start.slice(11), endTime: end.slice(11), repeat: 'none'
  }
  error.value = ''
  details.value.close()
  await nextTick()
  editor.value.showModal()
}

function create(day, hour) {
  const start = fromKey(day)
  start.setHours(hour, 0, 0, 0)
  return showEditor({
    title: '', description: '', category: 'auto', is_fixed: false, is_all_day: false,
    start: start.toISOString(), end: new Date(+start + 60 * 60 * 1000).toISOString()
  })
}

function closeEditor() {
  if (busy.value) return
  editor.value.close()
  draft.value = null
  selected.value = null
  error.value = ''
}

async function askScope(action) {
  error.value = ''
  scope.value = 'occurrence'
  scopeAction.value = action
  await nextTick()
  scopeDialog.value.showModal()
}

function closeScope() {
  if (busy.value) return
  scopeDialog.value.close()
  scopeAction.value = ''
  error.value = ''
}

function seriesOptions(task) {
  if (!isSeries(task)) return undefined
  return { scope: scope.value, occurrence_start: task.occurrence_start || task.series_original_start || task.start }
}

async function apply(action) {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    if (action === 'delete') {
      await deleteTask(selected.value.id, seriesOptions(selected.value))
    } else {
      const task = draft.value
      const category = task.category === 'auto'
        ? (await request('/todos/classify', 'POST', { title: task.title, description: task.description || '' })).category
        : task.category
      const data = taskPayload({
        ...task, category, recurrence: null,
        start: inputValue(task.startDate, task.startTime, task.start, task.is_all_day),
        end: inputValue(task.endDate, task.endTime, task.end, task.is_all_day, true)
      })
      if (task.id) await updateTask(task.id, data, seriesOptions(task))
      else await createTask(data)
    }
    scopeDialog.value.close()
    editor.value.close()
    details.value.close()
    scopeAction.value = ''
    selected.value = null
    draft.value = null
    emit('refresh')
  } catch (failure) {
    error.value = failure.message
  } finally {
    busy.value = false
  }
}

function save() {
  return isSeries(draft.value) ? askScope('save') : apply('save')
}

function remove() {
  return isSeries(selected.value) ? askScope('delete') : apply('delete')
}

defineExpose({ preview, create })
</script>

<template>
  <Teleport to="body">
    <dialog ref="details" class="event-details" :style="position" aria-labelledby="event-preview-title"
      @cancel.prevent="closeDetails" @click.self="closeDetails">
      <div v-if="selected" class="preview-body">
        <div class="preview-actions">
          <button type="button" class="event-icon" title="Редактировать" aria-label="Редактировать событие"
            :disabled="busy" autofocus @click="showEditor(selected)">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m4 16 11-11 4 4L8 20H4zm9-9 4 4m0-8 1-1 4 4-1 1"/></svg>
          </button>
          <button type="button" class="event-icon" title="Удалить" aria-label="Удалить событие" :disabled="busy" @click="remove">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M9 7V4h6v3m3 0-1 13H7L6 7m4 3v7m4-7v7"/></svg>
          </button>
          <button type="button" class="event-icon" title="Закрыть" aria-label="Закрыть карточку" :disabled="busy" @click="closeDetails">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18"/></svg>
          </button>
        </div>
        <div class="preview-heading">
          <i class="event-marker" aria-hidden="true"></i>
          <div>
            <h2 id="event-preview-title">{{ selected.title }}</h2>
            <p class="preview-period">{{ period(selected) }}</p>
            <p v-if="isSeries(selected)" class="preview-muted">{{ repeatLabel(selected) }}</p>
          </div>
        </div>
        <p v-if="selected.description" class="preview-description">{{ selected.description }}</p>
        <p class="preview-category">{{ categoryLabel(selected.category) }}<span v-if="selected.is_fixed"> · Нельзя переносить</span></p>
        <p v-if="error && !scopeAction" class="editor-error" role="alert">{{ error }}</p>
      </div>
    </dialog>

    <dialog ref="editor" class="calendar-editor" aria-labelledby="calendar-editor-title" @cancel.prevent="closeEditor">
      <form v-if="draft" class="calendar-form" @submit.prevent="save">
        <header class="editor-toolbar">
          <button type="button" class="event-icon" title="Вернуться к календарю" aria-label="Закрыть редактор"
            :disabled="busy" @click="closeEditor">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18"/></svg>
          </button>
          <span id="calendar-editor-title">{{ draft.id ? 'Редактирование события' : 'Новое событие' }}</span>
          <button class="editor-primary" :disabled="busy">{{ busy ? 'Сохраняю…' : 'Сохранить' }}</button>
        </header>

        <main class="editor-content">
          <label class="editor-title-field">
            <span class="visually-hidden">Название</span>
            <input v-model="draft.title" maxlength="200" placeholder="Добавьте название" required autofocus>
          </label>

          <section class="event-schedule" aria-label="Дата и время">
            <div class="date-group">
              <label for="calendar-start-date">Начало</label>
              <div class="date-controls">
                <input id="calendar-start-date" v-model="draft.startDate" type="date" required aria-label="Дата начала">
                <input v-if="!draft.is_all_day" v-model="draft.startTime" type="time" required aria-label="Время начала">
              </div>
            </div>
            <div class="date-group">
              <label for="calendar-end-date">{{ draft.is_all_day ? 'Последний день' : 'Окончание' }}</label>
              <div class="date-controls">
                <input id="calendar-end-date" v-model="draft.endDate" type="date" required aria-label="Дата окончания">
                <input v-if="!draft.is_all_day" v-model="draft.endTime" type="time" required aria-label="Время окончания">
              </div>
            </div>
          </section>

          <div class="repeat-row">
            <span v-if="draft.is_all_day" class="all-day-tag">Весь день</span>
            <p v-if="isSeries(draft)">{{ repeatLabel(draft) }}</p>
            <label v-else-if="!draft.is_all_day">
              <span class="visually-hidden">Повторение</span>
              <select v-model="draft.repeat">
                <option value="none">Не повторяется</option>
                <option value="daily">Каждый день</option>
                <option value="weekly">Каждую неделю</option>
              </select>
            </label>
          </div>

          <section class="editor-fields" aria-labelledby="event-fields-title">
            <h2 id="event-fields-title">Сведения о событии</h2>
            <label>Описание
              <textarea v-model="draft.description" maxlength="5000" placeholder="Добавьте описание" rows="5"></textarea>
            </label>
            <label class="category-field">Категория
              <select v-model="draft.category">
                <option v-if="!draft.id" value="auto">Определить с помощью ИИ</option>
                <option v-for="item in categories" :key="item.value" :value="item.value">{{ item.label }}</option>
              </select>
            </label>
            <label class="fixed-field">
              <input v-model="draft.is_fixed" type="checkbox">
              <span>Нельзя переносить <small>ИИ пропустит это событие при подборе переносов.</small></span>
            </label>
          </section>
          <p v-if="error && !scopeAction" class="editor-error" role="alert">{{ error }}</p>
        </main>
      </form>
    </dialog>

    <dialog ref="scopeDialog" class="calendar-scope" aria-labelledby="scope-dialog-title"
      @cancel.prevent="closeScope" @click.self="closeScope">
      <form v-if="scopeAction" class="scope-form" @submit.prevent="apply(scopeAction)">
        <h2 id="scope-dialog-title">{{ scopeAction === 'delete' ? 'Удалить повторяющееся событие' : 'Изменить повторяющееся событие' }}</h2>
        <fieldset :disabled="busy">
          <legend class="visually-hidden">Какие события изменить</legend>
          <label><input v-model="scope" type="radio" value="occurrence" name="event-scope" autofocus> Только это событие</label>
          <label><input v-model="scope" type="radio" value="series" name="event-scope"> Вся серия</label>
        </fieldset>
        <p v-if="error" class="editor-error" role="alert">{{ error }}</p>
        <div class="scope-actions">
          <button class="editor-secondary" type="button" :disabled="busy" @click="closeScope">Отмена</button>
          <button class="editor-primary" :class="{'editor-danger': scopeAction === 'delete'}" :disabled="busy">
            {{ scopeAction === 'delete' ? 'Удалить' : 'Сохранить' }}
          </button>
        </div>
      </form>
    </dialog>
  </Teleport>
</template>

<style scoped>
.event-details, .calendar-editor, .calendar-scope {
  --editor-accent: #0b57d0;
  --editor-text: #202124;
  --editor-muted: #5f6368;
  --editor-line: #dadce0;
  border: 0;
  padding: 0;
  color: var(--editor-text);
  background: #fff;
}

.event-details {
  position: fixed;
  inset: auto;
  margin: 0;
  width: min(420px, calc(100vw - 24px));
  max-width: none;
  max-height: min(560px, calc(100dvh - 24px));
  border-radius: 16px;
  box-shadow: 0 8px 28px #2021243b, 0 2px 8px #20212422;
}
.event-details::backdrop { background: transparent; }
.preview-body { padding: 10px 18px 18px; }
.preview-actions { display: flex; justify-content: flex-end; gap: 2px; }
.event-icon {
  display: inline-grid;
  width: 38px;
  height: 38px;
  place-items: center;
  flex: 0 0 auto;
  border-radius: 50%;
  color: #444746;
}
.event-icon svg { width: 20px; height: 20px; fill: none; stroke: currentColor; stroke-width: 1.7; stroke-linecap: round; stroke-linejoin: round; }
.event-icon:hover { background: #edf0f4; }
.preview-heading { display: flex; gap: 14px; align-items: baseline; margin: 2px 0 12px; }
.event-marker { width: 13px; height: 13px; flex: 0 0 auto; border-radius: 4px; background: var(--editor-accent); }
.preview-heading h2 { margin: 0; font-size: 21px; line-height: 1.3; font-weight: 550; overflow-wrap: anywhere; }
.preview-period { margin: 5px 0 0; line-height: 1.4; }
.preview-muted { margin: 5px 0 0; color: var(--editor-muted); }
.preview-description, .preview-category { margin: 10px 0 0 27px; overflow-wrap: anywhere; }
.preview-description { white-space: pre-wrap; }
.preview-category { color: var(--editor-muted); font-size: 13px; }

.calendar-editor {
  position: fixed;
  inset: 0;
  margin: 0;
  width: 100vw;
  max-width: none;
  height: 100dvh;
  max-height: none;
}
.calendar-form { min-height: 100%; }
.editor-toolbar {
  position: sticky;
  top: 0;
  z-index: 1;
  display: flex;
  align-items: center;
  gap: 12px;
  min-height: 64px;
  padding: 8px max(16px, calc((100vw - 1000px) / 2));
  border-bottom: 1px solid var(--editor-line);
  background: #fff;
}
.editor-toolbar span { font-size: 16px; }
.editor-toolbar .editor-primary { margin-left: auto; }
.editor-primary, .editor-secondary {
  min-height: 38px;
  padding: 8px 19px;
  border-radius: 20px;
  font-weight: 600;
}
.editor-primary { color: #fff; background: var(--editor-accent); }
.editor-primary:hover { background: #0847ab; }
.editor-secondary { color: var(--editor-accent); }
.editor-secondary:hover { background: #edf3fe; }
.editor-danger { background: #b3261e; }
.editor-danger:hover { background: #8c1d18; }

.editor-content { max-width: 940px; margin: 0 auto; padding: 30px 26px 42px; }
.editor-title-field { display: block; margin-bottom: 20px; }
.editor-title-field input {
  width: 100%;
  border: 0;
  border-bottom: 1px solid var(--editor-line);
  border-radius: 0;
  background: transparent;
  padding: 10px 0;
  color: inherit;
  font-size: clamp(24px, 4vw, 32px);
}
.calendar-editor :is(input, textarea, select, button):focus-visible,
.calendar-scope :is(input, button):focus-visible,
.event-details button:focus-visible { outline-color: var(--editor-accent); }
.editor-title-field input:focus-visible { outline: none; box-shadow: 0 1px var(--editor-accent); border-color: var(--editor-accent); }
.event-schedule { display: flex; flex-wrap: wrap; gap: 14px 26px; }
.date-group { display: grid; gap: 6px; }
.date-group label { font-size: 13px; color: var(--editor-muted); }
.date-controls { display: flex; flex-wrap: wrap; gap: 6px; }
.date-controls input, .repeat-row select, .editor-fields select, .editor-fields textarea {
  min-height: 40px;
  min-width: 0;
  padding: 8px 10px;
  border: 1px solid var(--editor-line);
  border-radius: 7px;
  background: #fff;
  color: inherit;
}
.repeat-row { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; min-height: 40px; margin-top: 12px; }
.repeat-row p { margin: 0; color: var(--editor-muted); }
.all-day-tag { background: #eef3fb; border-radius: 14px; padding: 4px 10px; color: #174378; }
.editor-fields { display: grid; gap: 16px; margin-top: 22px; }
.editor-fields h2 { margin: 0; padding: 9px 0; border-bottom: 1px solid var(--editor-line); font-size: 16px; font-weight: 600; }
.editor-fields label { display: grid; gap: 6px; }
.editor-fields textarea { width: 100%; resize: vertical; }
.category-field { max-width: 340px; }
.editor-fields .fixed-field { display: flex; align-items: flex-start; gap: 8px; }
.fixed-field input { margin: 3px 0 0; }
.fixed-field small { display: block; margin-top: 4px; color: var(--editor-muted); }
.editor-error { margin: 12px 0 0; color: #b3261e; }

.calendar-scope { width: min(400px, calc(100vw - 24px)); border-radius: 20px; box-shadow: 0 10px 35px #20212433; }
.calendar-scope::backdrop { background: #2021244d; }
.scope-form { padding: 22px; }
.scope-form h2 { margin: 0 0 14px; font-size: 19px; font-weight: 600; }
.scope-form fieldset { display: grid; gap: 12px; padding: 4px 0; margin: 0; border: 0; }
.scope-form label { display: flex; align-items: center; gap: 9px; }
.fixed-field input, .scope-form input {
  width: 16px;
  height: 16px;
  flex: 0 0 16px;
  padding: 0;
  accent-color: var(--editor-accent);
}
.scope-actions { display: flex; justify-content: flex-end; gap: 6px; margin-top: 20px; }
.visually-hidden { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip-path: inset(50%); white-space: nowrap; }

@media (max-width: 640px) {
  .event-details { inset: auto 12px 12px !important; width: auto; max-height: 60dvh; }
  .editor-content { padding: 18px 16px 28px; }
  .editor-toolbar { gap: 6px; padding-inline: 10px; }
  .editor-toolbar span { font-size: 14px; }
}
</style>