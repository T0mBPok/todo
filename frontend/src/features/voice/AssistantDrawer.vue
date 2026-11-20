<script setup>
import { nextTick, onMounted, onUnmounted, ref, watch } from 'vue'

import MenuIcon from '../../shared/MenuIcon.vue'

const props = defineProps({ open: Boolean, title: { type: String, default: 'Помощник' } })
const emit = defineEmits(['close'])
const panel = ref(null)
let previousFocus, animation, version=0
async function sync() {
  const current=++version
  await nextTick()
  if (!panel.value || current!==version) return
  animation?.cancel()
  const reduced=window.matchMedia('(prefers-reduced-motion: reduce)').matches
  if (props.open) {
    if (!panel.value.open) {
      previousFocus=document.activeElement
      panel.value.showModal()
    }
    panel.value.dataset.motion='opening'
    animation=panel.value.animate([{transform:'translateX(100%)',opacity:.6},{transform:'translateX(0)',opacity:1}],
      {duration:reduced?0:240,easing:'cubic-bezier(.2,.8,.2,1)'})
  } else if (panel.value.open) {
    panel.value.dataset.motion='closing'
    animation=panel.value.animate([{transform:'translateX(0)',opacity:1},{transform:'translateX(100%)',opacity:.6}],
      {duration:reduced?0:180,easing:'cubic-bezier(.4,0,1,1)'})
    try {await animation.finished} catch (_) {return}
    if (current===version && !props.open && panel.value) {
      panel.value.close()
      previousFocus?.focus()
    }
  }
}
onUnmounted(()=>{version++;animation?.cancel()})
watch(() => props.open, sync)
onMounted(sync)
function backdrop(event) { if (event.target === panel.value) emit('close') }
</script>
<template>
  <Teleport to="body">
    <dialog ref="panel" class="assistant-drawer" aria-labelledby="assistant-title" @cancel.prevent="emit('close')" @click="backdrop">
      <div class="assistant-shell">
        <header class="assistant-heading">
          <div><span class="eyebrow">ИМПУЛЬС / ПОМОЩНИК</span><h2 id="assistant-title">{{ title }}</h2></div>
          <button type="button" class="icon-button drawer-close" aria-label="Закрыть меню помощника" @click="emit('close')"><MenuIcon open /></button>
        </header>
        <div class="assistant-body"><slot /></div>
      </div>
    </dialog>
  </Teleport>
</template>
