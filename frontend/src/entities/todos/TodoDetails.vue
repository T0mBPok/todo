<script setup>
import { ref, nextTick } from 'vue'
import { request } from '../../shared/api.js'
import { errorMessage } from '../../shared/errors.js'
import { categoryLabel } from '../../shared/categories.js'
import { todoDisplayTitle, todoScheduleLabel } from './calendar.js'

const emit = defineEmits(['saved', 'edit'])
const dialog = ref(null), task = ref(null), busy = ref(false), error = ref('')
async function open(value) {
  if (busy.value) return
  task.value = {...value}
  error.value = ''
  await nextTick()
  dialog.value.showModal()
}
function close() { if (!busy.value) dialog.value.close() }
function edit() { close(); emit('edit', task.value) }
async function complete() {
  if (busy.value || !task.value) return
  busy.value = true
  error.value = ''
  try {
    const id = task.value.todo_id || task.value.id
    const saved = await request('/todos/'+id+'/completion', 'PATCH', {completed: !task.value.completed})
    dialog.value.close()
    emit('saved', saved)
  } catch (failure) { error.value = errorMessage(failure) }
  finally { busy.value = false }
}
defineExpose({open})
</script>

<template>
  <dialog ref="dialog" class="todo-details" aria-labelledby="todo-details-title"
    @click="$event.target===dialog && close()" @cancel="busy && $event.preventDefault()">
    <section v-if="task" class="todo-details-body">
      <header><span>ЗАДАЧА</span><button type="button" class="icon-button" aria-label="Закрыть задачу" :disabled="busy" @click="close">×</button></header>
      <h2 id="todo-details-title">{{ todoDisplayTitle(task) }}</h2>
      <p class="todo-details-schedule">{{ todoScheduleLabel(task) }}</p>
      <p class="todo-details-priority">{{ categoryLabel(task.category) }}</p>
      <p v-if="task.description" class="todo-details-description">{{ task.description }}</p>
      <p v-if="task.completed" class="todo-details-status">✓ Задача выполнена</p>
      <p v-if="error" class="todo-details-error" role="alert">{{ error }}</p>
      <footer>
        <button type="button" class="outline-button" :disabled="busy" @click="edit">Изменить</button>
        <button type="button" class="primary-button" :disabled="busy" @click="complete">{{ busy ? 'Сохраняю…' : task.completed ? 'Вернуть в работу' : 'Выполнено' }}</button>
      </footer>
    </section>
  </dialog>
</template>

<style scoped>
.todo-details{border:1px solid var(--line);border-radius:22px;padding:0;background:var(--paper,#fffcf8);color:var(--ink,#26212c);width:min(440px,calc(100vw - 24px));max-height:90dvh;box-shadow:0 24px 80px #241c2833}
.todo-details::backdrop{background:#241c2855}
.todo-details-body{padding:20px;display:grid;gap:12px}
.todo-details header,.todo-details footer{display:flex;align-items:center;justify-content:space-between;gap:10px}
.todo-details header>span{font-size:11px;letter-spacing:.14em;color:var(--muted)}
.todo-details h2{font-size:22px;line-height:1.3;overflow-wrap:anywhere}
.todo-details-schedule,.todo-details-priority{color:var(--muted);font-size:13px}
.todo-details-description{white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.6}
.todo-details-status{color:#36734c}.todo-details-error{color:#b3261e}
.todo-details footer{margin-top:8px;flex-wrap:wrap}.todo-details footer>button{flex:1;min-height:44px}
.todo-details footer>.primary-button{background:var(--obsidian,#25202a);color:#fff;border:1px solid transparent}
@media(max-width:760px){.todo-details{margin:auto auto 0;width:100%;max-width:100%;border-radius:22px 22px 0 0}.todo-details-body{padding:22px 20px max(22px,env(safe-area-inset-bottom))}}
</style>
