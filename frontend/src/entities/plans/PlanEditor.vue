<script setup>
import { computed, ref } from 'vue'
import { categories } from '../../shared/categories'
import { confirmPlan } from './api'
import { localDate, taskPayload } from '../../shared/api'

const props = defineProps({ plan: { type: Object, required: true } })
const emit = defineEmits(['saved', 'error'])
const reviews = new Map((props.plan.review || []).map(review => [review.task_index, review]))
const tasks = ref(props.plan.tasks.map((task, index) => ({
  ...task,
  index,
  review: reviews.get(index),
  start: localDate(task.start),
  end: localDate(task.end),
  repeat: task.recurrence?.frequency || 'none'
})))
const groups = computed(() => [
  { key: 'review', title: 'Нужно проверить', tasks: tasks.value.filter(task => task.review) },
  { key: 'clear', title: 'Распознано уверенно', tasks: tasks.value.filter(task => !task.review) }
].filter(group => group.tasks.length))
const form = ref(null)
const editingIndex = ref(null)
const busy = ref(false)
const dateFormatter = new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'short' })
const timeFormatter = new Intl.DateTimeFormat('ru-RU', { hour: '2-digit', minute: '2-digit' })

function formatPeriod(startValue, endValue) {
  const start = new Date(startValue)
  const end = new Date(endValue)
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) return 'Укажите дату и время'

  const first = dateFormatter.format(start)
  const last = dateFormatter.format(end)
  const from = timeFormatter.format(start)
  const to = timeFormatter.format(end)
  return start.toDateString() === end.toDateString()
    ? `${first} · ${from}–${to}`
    : `${first}, ${from} — ${last}, ${to}`
}

function toggleEditor(index) {
  if (editingIndex.value !== null && !form.value.reportValidity()) return
  editingIndex.value = editingIndex.value === index ? null : index
}

function applyOption(task, option) {
  task.start = localDate(option.start)
  task.end = localDate(option.end)
}

function removeTask(index) {
  tasks.value = tasks.value.filter(task => task.index !== index)
  editingIndex.value = null
}

async function save() {
  if (busy.value || !form.value?.reportValidity()) return
  busy.value = true
  try {
    const saved = await confirmPlan(props.plan.id, tasks.value.map(task => taskPayload({ ...task, recurrence: null })))
    emit('saved', tasks.value[0].start.slice(0, 10), saved)
  } catch (error) {
    emit('error', error.message)
  } finally {
    busy.value = false
  }
}

defineExpose({ save })
</script>

<template>
  <form ref="form" @submit.prevent="save" class="preview">
    <h2>Предпросмотр изменений</h2>
    <section v-for="group in groups" :key="group.key" class="review-group" :class="'review-' + group.key">
      <h3>{{ group.title }} <span>{{ group.tasks.length }}</span></h3>
      <article v-for="task in group.tasks" :key="task.index" class="review-card">
        <header class="review-row">
          <div class="review-summary">
            <strong>{{ task.title || 'Событие' }}</strong>
            <span>{{ formatPeriod(task.start, task.end) }}</span>
          </div>
          <button
            type="button"
            class="edit-toggle"
            :disabled="busy"
            :aria-expanded="editingIndex === task.index"
            :aria-controls="'plan-event-' + task.index"
            :aria-label="(editingIndex === task.index ? 'Свернуть: ' : 'Редактировать: ') + task.title"
            :title="editingIndex === task.index ? 'Свернуть' : 'Редактировать'"
            @click="toggleEditor(task.index)"
          >
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path v-if="editingIndex === task.index" d="m6 14 6-6 6 6"/>
              <path v-else d="m4 16 11-11 4 4L8 20H4zm9-9 4 4m0-8 1-1 4 4-1 1"/>
            </svg>
          </button>
        </header>
        <div :id="'plan-event-' + task.index">
          <fieldset v-if="editingIndex === task.index" :disabled="busy" class="draft editor-fields">
            <p v-if="task.review" class="review-reason">{{ task.review.reason }}</p>
            <div v-if="task.review?.options.length" class="time-options">
              <button
                v-for="option in task.review.options"
                :key="option.start + option.end"
                type="button"
                class="outline-button"
                :aria-pressed="task.start === localDate(option.start) && task.end === localDate(option.end)"
                @click="applyOption(task, option)"
              >{{ formatPeriod(option.start, option.end) }}</button>
            </div>
            <label>Название<input v-model="task.title" maxlength="200" required></label>
            <label>Описание<textarea v-model="task.description" maxlength="5000"></textarea></label>
            <div class="row">
              <label>Начало<input v-model="task.start" type="datetime-local" required></label>
              <label>Конец<input v-model="task.end" type="datetime-local" :min="task.start" required></label>
            </div>
            <div class="row">
              <label>Категория<select v-model="task.category"><option v-for="category in categories" :key="category.value" :value="category.value">{{ category.label }}</option></select></label>
              <label>Повторение<select v-model="task.repeat"><option value="none">Не повторяется</option><option value="daily">Каждый день</option><option value="weekly">Каждую неделю</option></select></label>
            </div>
            <div class="editor-actions">
              <button v-if="tasks.length > 1" type="button" class="link" @click="removeTask(task.index)">Убрать из плана</button>
              <button type="button" class="outline-button" @click="toggleEditor(task.index)">Готово</button>
            </div>
          </fieldset>
        </div>
      </article>
    </section>
    <button :disabled="busy">{{ busy ? 'Сохраняю…' : 'Сохранить изменения' }}</button>
  </form>
</template>

<style scoped>
.review-group { margin: 14px 0; }
.review-group h3 { display: flex; align-items: center; gap: 7px; margin-bottom: 6px; font-size: 13px; }
.review-group h3 span { min-width: 21px; padding: 1px 5px; border-radius: 10px; background: #ece8e3; text-align: center; font-size: 11px; }
.review-review h3 span { background: #f9e5d2; color: #78390f; }
.review-card { margin: 4px 0; border: 1px solid var(--line); border-radius: 8px; }
.review-review .review-card { border-left: 3px solid #d99b65; }
.review-row { display: flex; align-items: center; gap: 8px; justify-content: space-between; padding: 4px 5px 4px 9px; }
.review-summary { min-width: 0; line-height: 1.35; }
.review-summary strong { display: block; font-size: 13px; font-weight: 600; overflow-wrap: anywhere; }
.review-summary span { display: block; margin-top: 2px; color: var(--muted); font-size: 11px; font-variant-numeric: tabular-nums; }
.edit-toggle { display: grid; width: 36px; height: 36px; flex: 0 0 auto; place-items: center; padding: 0; border-radius: 6px; color: var(--muted); }
.edit-toggle:hover, .edit-toggle[aria-expanded="true"] { background: #f8ede5; color: var(--ember); }
.edit-toggle svg { width: 17px; height: 17px; fill: none; stroke: currentColor; stroke-width: 1.7; stroke-linecap: round; stroke-linejoin: round; }
.editor-fields { min-width: 0; margin: 0; padding: 12px; border: 0; border-top: 1px solid var(--line); border-radius: 0 0 7px 7px; background: transparent; }
.editor-fields select { display: block; width: 100%; margin-top: 7px; }
.editor-actions { display: flex; align-items: center; justify-content: flex-end; gap: 10px; font-size: 12px; }
.review-reason { margin: 0 0 10px; color: #78390f; font-size: 13px; overflow-wrap: anywhere; }
.time-options { display: flex; flex-wrap: wrap; gap: 6px; margin: 0 0 10px; }
.time-options button { text-align: left; font-size: 12px; }
.time-options button[aria-pressed="true"] { border-color: #a54d21; background: #f9e5d2; }
</style>
