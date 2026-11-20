<script setup>
import { ref, nextTick, onMounted, onUnmounted } from 'vue'
const props=defineProps({modelValue:{type:String,default:'week'}})
const emit=defineEmits(['update:modelValue'])
const items=[['day','День'],['three','3 дня'],['week','Неделя'],['month','Месяц']]
const open=ref(false),root=ref(null),trigger=ref(null),buttons=ref([])
async function show(last=false) {
  open.value=true
  await nextTick()
  const selected=items.findIndex(([value])=>value===props.modelValue)
  buttons.value[last?items.length-1:Math.max(0,selected)]?.focus()
}
function close(restore=false) { open.value=false;if(restore)trigger.value?.focus() }
function choose(value) { emit('update:modelValue',value);close(true) }
function outside(event) { if(!root.value?.contains(event.target))close() }
function focusOut(event) { if(!root.value?.contains(event.relatedTarget))close() }
function keys(event) {
  if(event.key==='Escape'){event.preventDefault();close(true);return}
  if(event.key==='Tab'){close();return}
  const index=buttons.value.indexOf(document.activeElement)
  let next
  if(event.key==='ArrowDown')next=(index+1)%items.length
  if(event.key==='ArrowUp')next=(index-1+items.length)%items.length
  if(event.key==='Home')next=0
  if(event.key==='End')next=items.length-1
  if(next!==undefined){event.preventDefault();buttons.value[next]?.focus()}
}
onMounted(()=>document.addEventListener('pointerdown',outside))
onUnmounted(()=>document.removeEventListener('pointerdown',outside))
</script>
<template>
  <div ref="root" class="period-picker" @focusout="focusOut">
    <button ref="trigger" type="button" class="period-trigger" :aria-label="'Вид календаря: '+(items.find(([value])=>value===modelValue)?.[1]||'Неделя')"
      aria-haspopup="menu" :aria-expanded="open" @click="open?close():show()" @keydown.down.prevent="show()" @keydown.up.prevent="show(true)">
      <span>{{ items.find(([value])=>value===modelValue)?.[1] }}</span>
      <svg :class="{rotated:open}" viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="m4 6 4 4 4-4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
    </button>
    <div v-if="open" class="period-menu" role="menu" aria-label="Вид календаря" @keydown="keys">
      <span class="period-caption" aria-hidden="true">Показывать</span>
      <button v-for="([value,label],index) in items" :key="value" :ref="el=>buttons[index]=el" type="button"
        role="menuitemradio" :aria-checked="modelValue===value" :class="{selected:modelValue===value}" @click="choose(value)">
        <span>{{ label }}</span><svg v-if="modelValue===value" viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="m3.5 8 3 3 6-6" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>
      </button>
    </div>
  </div>
</template>
<style scoped>
.period-picker { position:relative; order:5; flex:none; }
.period-picker .period-trigger { display:flex; align-items:center; justify-content:space-between; gap:9px; width:92px; height:32px; padding:0 10px; border:1px solid var(--line,#e9e3dc); border-radius:9px; background:var(--paper,#fffcf8); color:var(--ink,#25202a); font-size:12px; font-weight:500; }
.period-trigger svg { width:14px; height:14px; color:var(--muted); flex:none; transition:transform .15s; }
.period-trigger svg.rotated { transform:rotate(180deg); }
.period-picker .period-trigger:hover,.period-picker .period-trigger[aria-expanded=true] { border-color:#d3ad95; background:#fbf0e6; }
.period-menu { position:absolute; right:0; top:calc(100% + 8px); z-index:60; width:176px; padding:6px; border:1px solid var(--line,#e9e3dc); border-radius:13px; background:var(--paper,#fffcf8); box-shadow:0 8px 32px #25202a1c,0 2px 6px #25202a0a; }
.period-caption { display:block; padding:7px 10px 6px; color:var(--muted); font-size:10px; letter-spacing:.3px; }
.period-picker .period-menu button { display:flex; align-items:center; justify-content:space-between; width:100%; height:36px; padding:0 10px; border-radius:7px; font-size:13px; font-weight:400; text-align:left; }
.period-menu button svg { width:16px; height:16px; }
.period-picker .period-menu button:hover,.period-picker .period-menu button:focus-visible { background:#f7eee5; }
.period-picker .period-menu button.selected { background:#f5e5d8; color:#a3401b; font-weight:600; }
@media(max-width:999px) { .period-picker .period-trigger { width:70px; gap:3px; padding:0 6px; font-size:11px; } }
@media(max-width:760px) { .period-picker .period-trigger { width:63px; padding:0 4px; font-size:10px; } .period-menu { width:164px; } .period-picker .period-menu button { height:40px; } }
@media(prefers-reduced-motion:reduce) { .period-trigger svg { transition:none; } }
</style>
