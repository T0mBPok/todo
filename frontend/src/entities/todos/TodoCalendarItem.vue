<script setup>
import {computed} from 'vue'
import {todoDisplayTitle} from './calendar.js'
const props=defineProps({task:Object,compact:Boolean})
const title=computed(()=>todoDisplayTitle(props.task))
const emit=defineEmits(['open','complete'])
</script>
<template><div :class="['calendar-todo-chip',{completed:task.completed,compact}]" @click.stop>
<button type="button" class="calendar-todo-check" :aria-label="(task.completed?'Вернуть в работу: ':'Выполнить: ')+title" :aria-pressed="task.completed" @click.stop="emit('complete',task)">{{ task.completed?'✓':'' }}</button>
<button type="button" class="calendar-todo-open" @click.stop="emit('open',task)"><strong>{{ title }}</strong></button>
</div></template>
<style scoped>
.calendar-todo-chip{display:flex;flex-direction:row;gap:7px;align-items:flex-start;align-content:flex-start;justify-content:flex-start;min-width:0;padding:5px 7px;background:#fff5e9;border:1px solid #d58c5f;border-left:3px solid #b95024;border-radius:8px;box-sizing:border-box;overflow:hidden;color:#81391c;z-index:2}.calendar-todo-check{width:20px;height:20px;flex:0 0 20px;padding:0;border:1.5px solid #b95024;border-radius:50%;background:#fff;color:#fff;font-size:13px;line-height:18px}.completed .calendar-todo-check{background:#b95024}.calendar-todo-open{border:0;background:none;color:inherit;min-width:0;padding:0;text-align:left;display:grid;gap:3px;font:inherit;flex:1}.calendar-todo-open strong{font-size:14px;overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;line-height:1.25}.completed{opacity:.65}.completed strong{text-decoration:line-through}.compact{margin:2px 0;align-items:center;padding:3px 5px}.compact strong{-webkit-line-clamp:1}.compact .calendar-todo-check{width:17px;height:17px;flex-basis:17px;line-height:15px}
@media(max-width:760px){.compact .calendar-todo-check{display:none}.compact{gap:0}.compact .calendar-todo-open{min-height:24px;align-content:center}.calendar-todo-check{width:24px;height:24px;flex-basis:24px;line-height:22px}.calendar-todo-open strong{font-size:13px}}
</style>
