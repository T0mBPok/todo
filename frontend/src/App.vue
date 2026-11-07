<script setup>
import {ref} from 'vue'
import TodoApp from './entities/todos/TodoApp.vue'
import CalendarApp from './CalendarApp.vue'
const mode=ref('calendar')
</script>
<template><nav class="mode-switch" aria-label="Раздел приложения"><div class="impulse-brand"><span class="impulse-mark" aria-hidden="true">↯</span><span>Импульс<small>ЛИЧНЫЙ ПЛАНИРОВЩИК</small></span></div><button :class="{active:mode==='todos'}" @click="mode='todos'">✓ Задачи</button><button :class="{active:mode==='calendar'}" @click="mode='calendar'">▦ Календарь</button></nav><div class="mode-content"><TodoApp v-if="mode==='todos'"/><CalendarApp v-else/></div></template>
