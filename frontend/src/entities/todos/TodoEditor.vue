<script setup>
import { ref, nextTick } from 'vue'
import { request, localDate } from '../../shared/api.js'
import { errorMessage } from '../../shared/errors.js'
import {todoDisplayTitle} from './calendar.js'
import { categories } from '../../shared/categories.js'
const emit=defineEmits(['saved'])
const dialog=ref(null), form=ref(null), busy=ref(false), error=ref(''), deleting=ref(false)
const date=ref(''), time=ref(''), deadlineDate=ref(''), deadlineTime=ref('')
async function open(todo={}) {
  form.value={title:'',description:'',category:'important_not_urgent',completed:false,...todo,title:todoDisplayTitle(todo),id:todo.todo_id||todo.id}
  date.value=todo.scheduled_at?localDate(todo.scheduled_at).slice(0,10):todo.scheduled_date||''
  time.value=todo.scheduled_at?localDate(todo.scheduled_at).slice(11,16):''
  deadlineDate.value=todo.deadline_at?localDate(todo.deadline_at).slice(0,10):todo.deadline_date||''
  deadlineTime.value=todo.deadline_at?localDate(todo.deadline_at).slice(11,16):''
  error.value='';deleting.value=false
  await nextTick();dialog.value.showModal()
}
function create(day='') { return open({scheduled_date:day}) }
function close() { if(!busy.value) dialog.value.close() }
async function save() {
  if(!form.value.title.trim()||busy.value)return
  busy.value=true;error.value=''
  try {
    const scheduled_at=date.value&&time.value?new Date(date.value+'T'+time.value).toISOString():null
    const saved=await request('/todos'+(form.value.id?'/'+form.value.id:''),form.value.id?'PUT':'POST',{
      title:form.value.title,description:form.value.description,category:form.value.category,
      completed:form.value.completed,scheduled_date:date.value||null,scheduled_at,
      deadline_date:deadlineDate.value||null,
      deadline_at:deadlineDate.value&&deadlineTime.value?new Date(deadlineDate.value+'T'+deadlineTime.value).toISOString():null,
      timezone:Intl.DateTimeFormat().resolvedOptions().timeZone})
    dialog.value.close();emit('saved',saved)
  } catch(e) {error.value=errorMessage(e)} finally{busy.value=false}
}
async function remove() {
  if(!deleting.value){deleting.value=true;return}
  busy.value=true
  try{await request('/todos/'+form.value.id,'DELETE');dialog.value.close();emit('saved')}
  catch(e){error.value=errorMessage(e)}finally{busy.value=false}
}
function outside(event){if(event.target===dialog.value)close()}
async function requestDelete(todo){await open(todo);deleting.value=true}
defineExpose({open,create,requestDelete})
</script>
<template>
<dialog ref="dialog" class="todo-dialog" @click="outside" @cancel="busy&&$event.preventDefault()">
  <form v-if="form" class="todo-sheet" @submit.prevent="save">
    <header><div><span class="todo-sheet-eyebrow">ЗАДАЧА</span><h2>{{ form.id?'Детали задачи':'Новое дело' }}</h2></div><button type="button" class="icon-button" aria-label="Закрыть задачу" :disabled="busy" @click="close">×</button></header>
    <label>Что нужно сделать?<input v-model="form.title" required maxlength="200" autofocus placeholder="Например, сделать адаптив для мобилки"></label>
    <label v-if="form.id" class="todo-completion"><input type="checkbox" v-model="form.completed">Выполнено</label>
    <div class="todo-schedule-fields"><label>День<input type="date" v-model="date" @change="!date&&(time='')"></label><label><span>Время <small>необязательно</small></span><input type="time" v-model="time" :disabled="!date"></label></div>
    <p class="todo-sheet-hint">{{ !date?'Без даты — останется в списке задач.':time?'Появится в календаре в выбранное время.':'Появится в строке дня над расписанием.' }}</p>
    <button v-if="date" type="button" class="link" @click="date='';time=''">Убрать дату и время</button>
    <fieldset class="todo-deadline-fields"><legend>Дедлайн · крайний срок</legend>
      <div class="todo-schedule-fields"><label>До какого дня<input type="date" v-model="deadlineDate" @change="!deadlineDate&&(deadlineTime='')"></label><label><span>До какого времени <small>необязательно</small></span><input type="time" v-model="deadlineTime" :disabled="!deadlineDate"></label></div>
      <p class="todo-sheet-hint">Не меняет день выполнения. Без времени — до конца выбранного дня.</p>
      <button v-if="deadlineDate" type="button" class="link" @click="deadlineDate='';deadlineTime=''">Убрать дедлайн</button>
    </fieldset>
    <label>Подробности<textarea v-model="form.description" maxlength="5000" rows="3" placeholder="Что учесть…"></textarea></label>
    <label>Приоритет<select v-model="form.category"><option v-for="item in categories" :key="item.value" :value="item.value">{{ item.label }}</option></select></label>
    <p v-if="error" role="alert" class="todo-message">{{ error }}</p>
    <p v-if="deleting" role="alert">Удалить эту задачу из списка и календаря?</p>
    <footer><button v-if="form.id" type="button" class="link" :disabled="busy" @click="remove">{{ deleting?'Да, удалить':'Удалить' }}</button><button type="button" class="outline-button" :disabled="busy" @click="close">Отмена</button><button class="primary-button" :disabled="busy">{{ busy?'Сохраняю…':'Сохранить' }}</button></footer>
  </form>
</dialog>
</template>
<style scoped>
.todo-dialog{border:1px solid var(--line);border-radius:22px;padding:0;background:var(--paper,#fffcf8);color:var(--ink,#26212c);width:min(460px,calc(100vw - 32px));max-height:calc(100dvh - 40px);box-shadow:0 24px 80px #241c2833}
.todo-dialog::backdrop{background:#241c2855}
.todo-sheet{padding:24px;display:grid;gap:16px}.todo-sheet header,.todo-sheet footer{display:flex;align-items:center;gap:10px}.todo-sheet header>div{flex:1}.todo-sheet h2{font-size:22px;margin:4px 0}.todo-sheet-eyebrow{font-size:11px;letter-spacing:.14em;color:var(--muted)}
.todo-sheet label{margin:0;display:grid;gap:7px;font-size:14px}.todo-sheet input,.todo-sheet textarea,.todo-sheet select{margin:0;width:100%;min-width:0;box-sizing:border-box;border:1px solid var(--line);border-radius:10px;padding:11px;background:#fff;color:inherit;font:inherit}.todo-sheet textarea{height:90px;min-height:70px}.todo-sheet small,.todo-sheet-hint{color:var(--muted);font-size:12px}.todo-sheet-hint{margin:0;line-height:1.5}
.todo-deadline-fields{border:1px solid var(--line);border-radius:12px;margin:0;padding:12px;display:grid;gap:10px;min-width:0}.todo-deadline-fields legend{padding:0 5px;font-size:14px;font-weight:600}.todo-schedule-fields{display:grid;grid-template-columns:1fr 1fr;gap:12px}.todo-sheet .todo-completion{display:flex;align-items:center}.todo-completion input{width:20px;height:20px;accent-color:#bc4b21}.todo-sheet footer{justify-content:flex-end;flex-wrap:wrap}.todo-sheet footer>.link{margin-right:auto}
@media(max-width:760px){.todo-dialog{margin:auto auto 0;width:100%;max-width:100%;border-radius:22px 22px 0 0;max-height:92dvh}.todo-sheet{padding:22px 20px max(22px,env(safe-area-inset-bottom))}}
</style>
