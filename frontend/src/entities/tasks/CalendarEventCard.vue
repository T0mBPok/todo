<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { categoryLabel } from '../../shared/categories.js'
const props = defineProps({ task: {type:Object, required:true} })
const emit = defineEmits(['open'])
const card = ref(null), titleText = ref(null)
const showTime = ref(false), titleHeight = ref('none')
const time = value => new Date(value).toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'})
const tooltip = computed(() => props.task.title + ' · ' + categoryLabel(props.task.category) +
  ' · ' + time(props.task.start) + '–' + time(props.task.end))
let observer
function measure() {
  if (!card.value || !titleText.value) return
  const css = getComputedStyle(card.value)
  const available = card.value.clientHeight - parseFloat(css.paddingTop) - parseFloat(css.paddingBottom)
  const line = parseFloat(getComputedStyle(titleText.value).lineHeight) || 18
  const needed = titleText.value.scrollHeight
  // A time label is secondary: keep it only if the entire title also fits.
  showTime.value = !window.matchMedia('(max-width:760px)').matches && available >= 72 && needed + 16 <= available
  const lines = Math.max(1, Math.floor((available - (showTime.value ? 16 : 0)) / line))
  titleHeight.value = lines * line + 'px'
}
onMounted(() => {
  observer = new ResizeObserver(measure)
  observer.observe(card.value)
  observer.observe(titleText.value)
  measure()
})
onUnmounted(() => observer?.disconnect())
watch(() => [props.task.title, props.task.start, props.task.end], () => nextTick(measure))
</script>
<template>
  <button ref="card" type="button" class="calendar-event calendar-event-card"
    :class="{'title-priority':!showTime}" :style="{'--event-title-height':titleHeight}"
    :title="tooltip" :aria-label="tooltip" @click.stop="emit('open',$event)">
    <strong class="calendar-event-title"><span ref="titleText" class="event-title-text"><span v-if="task.is_fixed" aria-label="Нельзя переносить">🔒 </span><span v-if="task.recurrence" aria-label="Повторяющееся событие">↻ </span>{{ task.title }}</span></strong>
    <span v-if="showTime" class="calendar-event-time">{{ time(task.start) }} – {{ time(task.end) }}</span>
  </button>
</template>
<style scoped>
.calendar-event.calendar-event-card{display:flex;flex-direction:column;align-items:stretch;justify-content:flex-start;gap:2px;padding:4px 6px;text-align:left;min-width:0}
.calendar-event-card .calendar-event-title{display:block;flex:0 1 auto;min-height:0;max-height:var(--event-title-height,none);overflow:hidden;text-overflow:clip;white-space:normal;margin:0;font-size:14px;line-height:18px;font-weight:600}
.event-title-text{display:block;overflow-wrap:anywhere;line-height:inherit}
.calendar-event-card .calendar-event-time{flex:0 0 14px;font-size:11px;line-height:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin:0}
@media(max-width:760px){.calendar-event-card .calendar-event-title{font-size:13px;line-height:17px}.calendar-event-card .calendar-event-time{display:none}}
</style>
