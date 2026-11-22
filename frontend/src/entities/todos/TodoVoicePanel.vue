<script setup>
import { ref } from 'vue'
import { request } from '../../shared/api.js'
import { errorMessage } from '../../shared/errors.js'
import { useVoiceInput } from '../../features/voice/useVoiceInput.js'
import MicIcon from '../../features/voice/MicIcon.vue'
import TodoEditor from './TodoEditor.vue'
import { todoScheduleLabel } from './calendar.js'
const emit=defineEmits(['changed'])
const text=ref(''),message=ref(''),busy=ref(false),draft=ref(null),history=ref([]),saved=ref([]),editor=ref(null)
const {supported,listening,starting,processing,toggle,cancel,recordSeconds,audioUrl,rawTranscript}=useVoiceInput({text,onComplete:prepare,onError:value=>message.value=value})
async function execute(){
 if(!draft.value||busy.value)return
 busy.value=true
 try{const result=await request('/todos/commands/'+draft.value.id+'/execute','POST');saved.value=result.tasks;draft.value=null;message.value=result.note;emit('changed',result.tasks)}
 catch(e){message.value=errorMessage(e)}finally{busy.value=false}
}
async function prepare(){
 if(busy.value||!text.value.trim())return
 busy.value=true;message.value='Разбираю задачи…';saved.value=[];draft.value=null
 try{const result=await request('/todos/commands/prepare','POST',{text:text.value,timezone:Intl.DateTimeFormat().resolvedOptions().timeZone,history:history.value});history.value=[...history.value,{role:'user',text:text.value.slice(0,1500)},{role:'assistant',text:result.note.slice(0,1500)}].slice(-8);draft.value=result;message.value=result.note;busy.value=false;if(!result.requires_confirmation)await execute()}
 catch(e){message.value=errorMessage(e)}finally{busy.value=false}
}
function edited(todo){emit('changed',todo?[todo]:[]);saved.value=[];message.value='Задача обновлена.'}
</script>
<template><section class="todo-voice-panel">
<p class="todo-voice-intro">Расскажи, что нужно сделать. День и время можно назвать сразу — задача появится в календаре.</p>
<button :class="['record-main-button',{recording:listening}]" :disabled="!supported||busy||starting||processing" @click="toggle"><span class="mic-symbol"><MicIcon/></span><b>{{ listening?'Завершить · '+recordSeconds+' с':processing?'Распознаю…':'Создать задачу голосом' }}</b><small>«Сделать адаптив для мобилки 27-го числа в шесть вечера»</small></button>
<button v-if="listening||starting||processing" class="link" @click="cancel">Отменить запись</button>
<form @submit.prevent="prepare"><label>Что нужно сделать?<textarea class="voice-command-text" v-model="text" rows="6" maxlength="6000" :disabled="busy||listening||starting||processing" placeholder="Можно продиктовать или написать. Например: купить продукты завтра."></textarea></label><button class="primary-button" :disabled="busy||listening||starting||processing||!text.trim()">{{ busy?'Обрабатываю…':'Добавить задачи' }}</button></form>
<p v-if="message" role="status" class="todo-message">{{ message }}</p>
<section v-if="draft" class="todo-confirm"><h3>Проверь изменения</h3><article v-for="(op,i) in draft.operations" :key="i"><strong>{{ {create:'Добавить',update:'Изменить',delete:'Удалить',complete:'Выполнить',reopen:'Вернуть в работу'}[op.action.action] }}: {{ op.action.title||op.snapshot?.title }}</strong><small>{{ todoScheduleLabel(op.schedule||op.snapshot||{}) }}</small></article><button class="primary-button" :disabled="busy" @click="execute">Подтвердить</button><button class="outline-button" :disabled="busy" @click="draft=null">Отмена</button></section>
<div v-if="saved.length" class="todo-voice-results"><article v-for="task in saved" :key="task.id"><div><strong>{{ task.title }}</strong><small>{{ todoScheduleLabel(task) }}</small></div><button class="icon-button" :aria-label="'Изменить '+task.title" @click="editor.open(task)">✎</button></article></div>
<details v-if="audioUrl||rawTranscript"><summary>Запись и расшифровка</summary><audio v-if="audioUrl" :src="audioUrl" controls></audio><p>{{ rawTranscript }}</p></details>
<TodoEditor ref="editor" @saved="edited"/>
</section></template>
<style scoped>
.todo-voice-panel{display:grid;gap:18px}.todo-voice-intro{color:var(--muted);font-size:14px;line-height:1.6;margin:0}.todo-voice-panel form{display:grid;gap:14px}.todo-voice-panel label{margin:0;display:grid;gap:10px}.voice-command-text{width:100%;box-sizing:border-box;min-height:180px;resize:vertical;padding:15px;border:1px solid var(--line);border-radius:14px;background:var(--paper);font:inherit;color:inherit}.todo-voice-panel audio{width:100%}.todo-voice-results article,.todo-confirm article{display:flex;align-items:center;gap:10px;border-bottom:1px solid var(--line);padding:12px 0}.todo-voice-results article>div{flex:1}.todo-voice-panel small{display:block;color:var(--muted);margin-top:5px}.todo-confirm article{display:block}.todo-message{overflow-wrap:anywhere}
</style>
