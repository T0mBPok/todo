<script setup>
import { ref, watch } from 'vue'

defineOptions({ inheritAttrs: false })
const props = defineProps({ modelValue: { type: String, default: '' } })
const emit = defineEmits(['update:modelValue'])
const visible = ref(false)
watch(() => props.modelValue, value => { if (!value) visible.value = false })
</script>

<template>
  <span class="password-field">
    <input v-bind="$attrs" :type="visible ? 'text' : 'password'" :value="modelValue"
      @input="emit('update:modelValue', $event.target.value)">
    <button type="button" class="password-toggle" :aria-label="visible ? 'Скрыть пароль' : 'Показать пароль'"
      :aria-pressed="visible" :title="visible ? 'Скрыть пароль' : 'Показать пароль'" @click="visible = !visible">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z" />
        <circle cx="12" cy="12" r="3" />
        <path v-if="visible" d="m3 3 18 18" />
      </svg>
    </button>
  </span>
</template>

<style scoped>
.password-field { position:relative; display:block; width:100%; }
.password-field input { padding-right:48px; }
.account-card .password-toggle {
  position:absolute; top:50%; right:3px; transform:translateY(-50%);
  display:grid; place-items:center; width:40px; height:40px; min-height:40px;
  padding:9px; border:0; border-radius:8px; background:transparent; color:#776c76;
}
.account-card .password-toggle:hover { color:#ad4926; background:#ad49260c; }
.account-card .password-toggle:focus-visible { outline:2px solid #ad4926; outline-offset:-3px; }
.password-toggle svg { width:21px; height:21px; }
.password-field input::-ms-reveal { display:none; }
</style>
