<script setup>
import { ref } from 'vue'
import {categories} from '../../shared/categories'
import { confirmPlan } from './api'
import { localDate, taskPayload } from '../../shared/api'
const props = defineProps({ plan: { type: Object, required: true } })
const emit = defineEmits(['saved', 'error'])
const tasks = ref(props.plan.tasks.map(t => ({ ...t, start: localDate(t.start), end: localDate(t.end), repeat: t.recurrence?.frequency || 'none' })))
const busy = ref(false)
async function save() {
  busy.value = true
  try { await confirmPlan(props.plan.id, tasks.value.map(t=>taskPayload({...t,recurrence:null}))); emit('saved', tasks.value[0].start.slice(0, 10)) }
  catch (error) { emit('error', error.message) }
  finally { busy.value = false }
}
</script>
<template>
  <form @submit.prevent="save" class="preview">
    <h2>Проверь план</h2><p>{{ plan.note }}</p>
    <div v-for="(task, index) in tasks" :key="index" class="draft">
      <label>Задача<input v-model="task.title" maxlength="200" required></label>
      <label>Описание<textarea v-model="task.description" maxlength="5000"></textarea></label><div class="row"><label>Начало<input v-model="task.start" type="datetime-local" required></label><label>Конец<input v-model="task.end" type="datetime-local" required></label></div>
      <label>Категория<select v-model="task.category"><option v-for="c in categories" :key="c.value" :value="c.value">{{ c.label }}</option></select></label><label>Повторение<select v-model="task.repeat"><option value="none">Не повторяется</option><option value="daily">Каждый день · без окончания</option><option value="weekly">Каждую неделю · без окончания</option></select></label>
      <button v-if="tasks.length > 1" type="button" class="link" @click="tasks.splice(index, 1)">Убрать из плана</button>
    </div>
    <button :disabled="busy">{{ busy ? 'Сохраняю…' : 'Добавить в календарь' }}</button>
  </form>
</template>
