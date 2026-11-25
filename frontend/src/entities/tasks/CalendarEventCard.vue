<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { categoryLabel } from '../../shared/categories.js'
const props = defineProps({ task: {type:Object, required:true} })
const emit = defineEmits(['open','header-size'])
const card = ref(null), titleText = ref(null), timeLabel = ref(null)
const titleHeight = ref('0px'), compact = ref(false)
const time = value => new Date(value).toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'})
const tooltip = computed(() => props.task.title + ' · ' + categoryLabel(props.task.category) +
  ' · ' + time(props.task.start) + '–' + time(props.task.end))
let observer
function measure() {
  if (!card.value || !titleText.value) return
  const css = getComputedStyle(card.value)
  const available = card.value.clientHeight - parseFloat(css.paddingTop) - parseFloat(css.paddingBottom)
  const line = parseFloat(getComputedStyle(titleText.value).lineHeight) || 16
  const timeHeight = timeLabel.value.getBoundingClientRect().height
  const rowGap = timeHeight ? 2 : 0
  // Always reserve the time row; show only whole title lines above it.
  compact.value = card.value.clientHeight < 28
  const lines = Math.max(0, Math.floor((available - timeHeight - rowGap) / line))
  titleHeight.value = lines * line + 'px'
  const visibleTitle = Math.min(titleText.value.getBoundingClientRect().height, lines * line)
  emit('header-size', Math.ceil(parseFloat(css.paddingTop) + visibleTitle + timeHeight +
    (visibleTitle ? rowGap : 0) + parseFloat(css.paddingBottom) + 2))
}
onMounted(() => {
  observer = new ResizeObserver(measure)
  observer.observe(card.value)
  observer.observe(titleText.value)
  observer.observe(timeLabel.value)
  measure()
})
onUnmounted(() => observer?.disconnect())
watch(() => [props.task.title, props.task.start, props.task.end], () => nextTick(measure))
</script>
<template>
  <button ref="card" type="button" class="calendar-event calendar-event-card"
    :class="{'compact-event':compact}" :style="{'--event-title-height':titleHeight}"
    :title="tooltip" :aria-label="tooltip" @click.stop="emit('open',$event)">
    <strong v-show="titleHeight!=='0px'" class="calendar-event-title"><span ref="titleText" class="event-title-text"><span v-if="task.is_fixed" aria-label="Нельзя переносить">🔒 </span><span v-if="task.recurrence" aria-label="Повторяющееся событие">↻ </span>{{ task.title }}</span></strong>
    <span ref="timeLabel" class="calendar-event-time">{{ time(task.start) }} – {{ time(task.end) }}</span>
  </button>
</template>
<style scoped>
.calendar-event.calendar-event-card{display:flex;flex-direction:column;align-items:stretch;justify-content:flex-start;gap:2px;padding:4px 6px;text-align:left;min-width:0}
.calendar-event-card .calendar-event-title{display:block;flex:0 0 auto;min-height:0;max-height:var(--event-title-height,none);overflow:hidden;text-overflow:clip;white-space:normal;margin:0;font-size:13px;line-height:16px;font-weight:600}
.event-title-text{display:block;overflow-wrap:anywhere;line-height:inherit}
.calendar-event-card .calendar-event-time{display:block;flex:0 0 12px;font-size:10px;line-height:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin:0}
.calendar-event.calendar-event-card.compact-event{padding-top:1px;padding-bottom:1px;gap:0}
@media(max-width:760px){.calendar-event.calendar-event-card{border-left:0!important;padding:1px 2px;gap:0}.calendar-event-card .calendar-event-title{font-size:12px;line-height:15px}.calendar-event-card .calendar-event-time{display:none}}
</style>
