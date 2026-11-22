<script setup>
import { errorMessage } from '../../shared/errors.js'
import {ref,computed,onMounted,watch} from 'vue'
import {request} from '../../shared/api'
import MenuIcon from '../../shared/MenuIcon.vue'
import AssistantDrawer from '../../features/voice/AssistantDrawer.vue'
import TodoEditor from './TodoEditor.vue'
import TodoVoicePanel from './TodoVoicePanel.vue'
import {todoScheduleLabel,todoDisplayTitle} from './calendar.js'
import {categories,categoryLabel} from '../../shared/categories'
const props=defineProps({refreshToken:{type:Number,default:0}})
const assistantOpen=ref(false),todoEditor=ref(null)
const category=ref('important_not_urgent'),categoryFilter=ref('all')
const tasks=ref([]),title=ref(''),description=ref(''),message=ref(''),busy=ref(false),filter=ref('active')
const visible=computed(()=>tasks.value.filter(t=>(filter.value==='all'||(filter.value==='done'?t.completed:!t.completed))&&(categoryFilter.value==='all'||t.category===categoryFilter.value)))
const activeCount=computed(()=>tasks.value.filter(t=>!t.completed).length)
async function refresh(){tasks.value=await request('/todos')}
async function run(work){busy.value=true;try{await work();await refresh()}catch(error){message.value=errorMessage(error)}finally{busy.value=false}}
async function add(){if(!title.value.trim())return;await run(async()=>{await request('/todos','POST',{title:title.value,description:description.value,category:category.value});title.value='';description.value='';message.value='Задача добавлена.'})}
async function complete(task){await run(()=>request('/todos/'+task.id+'/completion','PATCH',{completed:!task.completed}))}
onMounted(()=>run(refresh))
watch(()=>props.refreshToken,()=>refresh().catch(e=>message.value=errorMessage(e)))
</script>
<template><main class="todo-app"><header class="todo-heading"><div><span class="todo-eyebrow">В СВОЁМ ТЕМПЕ</span><h1>Мои задачи</h1><p>{{ activeCount?activeCount+' в работе':'Можно начать с одного дела' }} · с датой или в своём темпе</p></div><button class="assistant-trigger" aria-label="Открыть меню ИИ для задач" :aria-expanded="assistantOpen" @click="assistantOpen=!assistantOpen"><MenuIcon :open="assistantOpen" /><span>Помощник</span><i></i></button></header>
<section class="todo-capture"><form @submit.prevent="add"><label for="todo-title">Что нужно сделать?</label><div class="todo-add-row"><input id="todo-title" v-model="title" maxlength="200" required placeholder="Например, закончить отчёт" :disabled="busy"><button class="primary-button" :disabled="busy||!title.trim()">Добавить</button></div><details class="todo-add-details"><summary>Описание и категория</summary><textarea v-model="description" aria-label="Описание новой задачи" maxlength="5000" placeholder="Подробности, если нужны…" :disabled="busy"></textarea><label>Категория<select v-model="category" :disabled="busy"><option v-for="c in categories" :key="c.value" :value="c.value">{{ c.label }}</option></select></label></details></form><button class="link" @click="todoEditor.create()">Добавить с датой и временем</button></section>
<AssistantDrawer :open="assistantOpen" title="Помощник задач" @close="assistantOpen=false"><TodoVoicePanel @changed="run(refresh)"/></AssistantDrawer>
<p v-if="message&&!assistantOpen" class="todo-message" role="status">{{ message }}</p>
<nav class="todo-filters" aria-label="Фильтр задач"><button :class="{active:filter==='active'}" @click="filter='active'">В работе · {{ activeCount }}</button><button :class="{active:filter==='done'}" @click="filter='done'">Выполнено · {{ tasks.length-activeCount }}</button><button :class="{active:filter==='all'}" @click="filter='all'">Все</button></nav>
<section class="priority-grid" aria-label="Категории задач"><button :class="{selected:categoryFilter==='all'}" @click="categoryFilter='all'">Все категории<span>{{ tasks.filter(t=>filter==='all'||(filter==='done'?t.completed:!t.completed)).length }}</span></button><button v-for="c in categories" :key="c.value" :data-category="c.value" :class="{selected:categoryFilter===c.value}" :aria-pressed="categoryFilter===c.value" @click="categoryFilter=c.value"><strong>{{ c.label }}</strong><small>{{ c.hint }}</small><span>{{ tasks.filter(t=>t.category===c.value&&(filter==='all'||(filter==='done'?t.completed:!t.completed))).length }}</span></button></section><section aria-label="Список задач"><div v-if="!visible.length" class="todo-empty"><span>✓</span><h2>{{ categoryFilter!=='all'?'В этой категории пока нет задач':filter==='done'?'Пока нет завершённых задач':'Здесь будут твои дела' }}</h2><p>Добавь первое дело. Подробности можно дописать позже.</p></div><article v-for="task in visible" :key="task.id" :class="['todo-item',{done:task.completed}]"><input type="checkbox" :checked="task.completed" :disabled="busy" :aria-label="(task.completed?'Вернуть в работу: ':'Выполнить: ')+task.title" @change="complete(task)"><div class="todo-item-body"><strong>{{ todoDisplayTitle(task) }}</strong><small class="todo-date-label">{{ todoScheduleLabel(task) }}</small><span class="priority-badge" :data-category="task.category">{{ categoryLabel(task.category) }}</span><p v-if="task.description">{{ task.description }}</p></div><button class="icon-button" :aria-label="'Изменить: '+task.title" :disabled="busy" @click="todoEditor.open(task)">✎</button><button class="icon-button" :aria-label="'Удалить: '+task.title" :disabled="busy" @click="todoEditor.requestDelete(task)">×</button></article></section>
<TodoEditor ref="todoEditor" @saved="run(refresh)"/></main></template>
