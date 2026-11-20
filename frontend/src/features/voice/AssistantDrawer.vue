<script setup>
import { nextTick, onMounted, ref, watch } from 'vue'

const props = defineProps({ open: Boolean, title: { type: String, default: 'Помощник' } })
const emit = defineEmits(['close'])
const panel = ref(null)
let previousFocus

async function sync() {
  await nextTick()
  if (props.open && !panel.value.open) {
    previousFocus = document.activeElement
    panel.value.showModal()
  } else if (!props.open && panel.value.open) {
    panel.value.close()
    previousFocus?.focus()
  }
}
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
          <button type="button" class="icon-button" aria-label="Закрыть меню помощника" @click="emit('close')">×</button>
        </header>
        <div class="assistant-body"><slot /></div>
      </div>
    </dialog>
  </Teleport>
</template>
