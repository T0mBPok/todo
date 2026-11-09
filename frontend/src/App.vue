<script setup>
import {nextTick, onMounted, ref} from 'vue'
import TodoApp from './entities/todos/TodoApp.vue'
import CalendarApp from './CalendarApp.vue'
import {request} from './shared/api.js'

const mode = ref('calendar')
const user = ref(null)
const ready = ref(false)
const registration = ref(false)
const email = ref('')
const password = ref('')
const pendingEmail = ref(null)
const code = ref('')
const verificationNotice = ref('')
const busy = ref(false)
const error = ref('')
const googleOpen = ref(false)
const google = ref(null)
const googleDialog = ref(null)
const googleTrigger = ref(null)
const googleImportOffer = ref(false)
const googleImportKinds = ref([])
const googleKinds = [['event', 'Календарь'], ['todo', 'Задачи']]
const syncBusy = ref(false)
const message = ref('')
const revision = ref(0)

async function loadUser() {
  error.value = ''
  try {
    user.value = await request('/auth/me')
  } catch (e) {
    if (e.status !== 401) error.value = e.message
  } finally {
    ready.value = true
  }
}

onMounted(async () => {
  await loadUser()
  const url = new URL(window.location.href)
  const callback = url.searchParams.get('google')
  if (callback) {
    url.searchParams.delete('google')
    url.searchParams.delete('reason')
    window.history.replaceState(null, '', url)
    if (user.value) {
      const connected = callback === 'connected'
      await openGoogle(connected ? '' : 'Google не подключён. Проверьте разрешения и попробуйте ещё раз.', connected)
    }
  }
})

async function authenticate() {
  busy.value = true
  error.value = ''
  try {
    const result = await request('/auth/' + (registration.value ? 'register' : 'login'), 'POST', {
      email: email.value, password: password.value
    })
    if (result.challenge) {
      pendingEmail.value = result
      code.value = ''
      verificationNotice.value = ''
    } else {
      user.value = result
    }
    password.value = ''
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = false
  }
}

async function confirmEmail() {
  busy.value = true
  error.value = ''
  verificationNotice.value = ''
  try {
    user.value = await request('/auth/verify-email', 'POST', {challenge: pendingEmail.value.challenge, code: code.value})
    pendingEmail.value = null
    code.value = ''
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = false
  }
}

async function resendEmail() {
  busy.value = true
  error.value = ''
  verificationNotice.value = ''
  try {
    await request('/auth/resend-email', 'POST', {challenge: pendingEmail.value.challenge})
    code.value = ''
    verificationNotice.value = 'Отправили новый код. Используйте последнее письмо.'
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = false
  }
}

function backToAccountForm() {
  pendingEmail.value = null
  code.value = ''
  error.value = ''
}

async function logout() {
  error.value = ''
  try {
    await request('/auth/logout', 'POST')
    user.value = null
    google.value = null
    googleOpen.value = false
    mode.value = 'calendar'
  } catch (e) {
    error.value = e.message
  }
}

async function openGoogle(notice = '', offerImport = false) {
  googleOpen.value = true
  google.value = null
  googleImportOffer.value = offerImport
  googleImportKinds.value = []
  message.value = notice
  try {
    google.value = await request('/google/status')
  } catch (e) {
    message.value = e.message
  }
  await nextTick()
  googleDialog.value?.focus()
}

function closeGoogle() {
  if (syncBusy.value) return
  googleOpen.value = false
  googleImportOffer.value = false
  nextTick(() => googleTrigger.value?.focus())
}

function syncSummary(result) {
  return 'Обновлено: ' + result.changed + '. Пропущено: ' + result.skipped +
    '. Конфликтов: ' + result.conflicts + '.' +
    (result.partial ? ' Обработана часть записей. Повторите обмен, чтобы продолжить.' : '')
}

async function importSelectedGoogleData() {
  if (syncBusy.value || !google.value?.connected || !googleImportKinds.value.length) return
  const selection = googleKinds.filter(([kind]) => googleImportKinds.value.includes(kind))
  syncBusy.value = true
  message.value = ''
  const results = []
  const retry = []
  try {
    for (const [kind, title] of selection) {
      try {
        const result = await request('/google/sync', 'POST', {direction: 'pull', kind})
        results.push(title + ': ' + syncSummary(result))
        if (result.partial) retry.push(kind)
      } catch (e) {
        results.push(title + ': ' + e.message)
        retry.push(kind)
      }
    }
    googleImportKinds.value = retry
    googleImportOffer.value = retry.length > 0
    message.value = results.join('\n')
    revision.value++
  } finally {
    syncBusy.value = false
  }
}

async function googleAction(action, payload) {
  syncBusy.value = true
  message.value = ''
  try {
    const result = await request('/google/' + action, 'POST', payload)
    if (action === 'connect') {
      window.location.assign(result.url)
    } else if (action === 'disconnect') {
      await openGoogle('Аккаунт Google отключён.')
    } else {
      if (payload.direction === 'pull' && result.changed) revision.value++
      message.value = syncSummary(result)
    }
  } catch (e) {
    message.value = e.message
    if (payload?.direction === 'pull') revision.value++
  } finally {
    syncBusy.value = false
  }
}
</script>

<template>
  <main v-if="!ready" class="account-screen" aria-busy="true">Загружаем приложение…</main>
  <main v-else-if="!user" class="account-screen">
    <form v-if="pendingEmail" class="account-card" @submit.prevent="confirmEmail">
      <h1>Подтвердите почту</h1>
      <p>Отправили восьмизначный код на <strong>{{ pendingEmail.email }}</strong>. Он действует до 10 минут.</p>
      <label>Код из письма<input v-model.trim="code" type="text" inputmode="numeric" pattern="[0-9]{8}"
        maxlength="8" autocomplete="one-time-code" required></label>
      <p v-if="error" role="alert">{{ error }}</p>
      <p v-if="verificationNotice" role="status">{{ verificationNotice }}</p>
      <button class="account-primary" :disabled="busy" type="submit">Подтвердить</button>
      <button type="button" :disabled="busy" @click="resendEmail">Отправить код ещё раз</button>
      <button type="button" :disabled="busy" @click="backToAccountForm">Назад</button>
    </form>
    <form v-else class="account-card" @submit.prevent="authenticate">
      <div class="impulse-brand"><span class="impulse-mark" aria-hidden="true">↯</span><span>Импульс</span></div>
      <h1>{{ registration ? 'Создать аккаунт' : 'Войти в Импульс' }}</h1>
      <label>Почта<input v-model.trim="email" type="email" maxlength="254" autocomplete="username" required></label>
      <label>Пароль<input v-model="password" type="password" :minlength="registration ? 15 : 1"
        maxlength="128" :autocomplete="registration ? 'new-password' : 'current-password'" required></label>
      <small v-if="registration">Минимум 15 символов.</small>
      <p v-if="error" role="alert">{{ error }}</p>
      <button class="account-primary" type="submit" :disabled="busy">{{ busy ? 'Подождите…' : registration ? 'Зарегистрироваться' : 'Войти' }}</button>
      <button type="button" :disabled="busy" @click="registration = !registration; error = ''">
        {{ registration ? 'Уже есть аккаунт' : 'Создать аккаунт' }}
      </button>
    </form>
  </main>
  <template v-else>
    <nav class="mode-switch" aria-label="Раздел приложения" :inert="googleOpen">
      <div class="impulse-brand"><span class="impulse-mark" aria-hidden="true">↯</span><span>Импульс<small>ЛИЧНЫЙ ПЛАНИРОВЩИК</small></span></div>
      <button :class="{active:mode==='todos'}" @click="mode='todos'">✓ Задачи</button>
      <button :class="{active:mode==='calendar'}" @click="mode='calendar'">▦ Календарь</button>
      <button ref="googleTrigger" @click="openGoogle()">Google</button>
      <button :title="user.email" @click="logout">Выйти</button>
    </nav>
    <p v-if="error" role="alert">{{ error }}</p>
    <div :key="revision" class="mode-content" :inert="googleOpen"><TodoApp v-if="mode==='todos'"/><CalendarApp v-else/></div>
    <div v-if="googleOpen" class="account-overlay" @click.self="closeGoogle">
      <section ref="googleDialog" class="account-card" role="dialog" aria-modal="true"
        aria-labelledby="google-dialog-title" tabindex="-1" @keydown.esc="closeGoogle">
        <button class="account-close" aria-label="Закрыть" :disabled="syncBusy" @click="closeGoogle">×</button>
        <h2 id="google-dialog-title">{{ googleImportOffer && google?.connected ? 'Google подключён' : 'Обмен с Google' }}</h2>
        <p v-if="google && !google.configured">Администратор ещё не настроил Google OAuth.</p>
        <form v-else-if="google?.connected && googleImportOffer" class="google-import" @submit.prevent="importSelectedGoogleData">
          <fieldset :disabled="syncBusy">
            <legend>Что загрузить из Google?</legend>
            <label class="google-import-choice" v-for="[kind, title] in googleKinds" :key="kind">
              <input v-model="googleImportKinds" type="checkbox" :value="kind">
              {{ title }}
            </label>
          </fieldset>
          <p>Можно выбрать оба пункта или вернуться к импорту позже.</p>
          <div class="google-actions">
            <button class="account-primary" type="submit" :disabled="syncBusy || !googleImportKinds.length">Загрузить выбранное</button>
            <button type="button" :disabled="syncBusy" @click="closeGoogle">Позже</button>
          </div>
        </form>
        <template v-else-if="google?.connected">
          <p>Основной календарь и список Google Tasks по умолчанию. Связанные записи обновляются при повторном обмене. Удаления не передаются.</p>
          <div class="google-actions" v-for="[kind, title] in googleKinds" :key="kind">
            <strong>{{ title }}</strong>
            <button :disabled="syncBusy" @click="googleAction('sync', {direction:'pull', kind})">Из Google</button>
            <button :disabled="syncBusy" @click="googleAction('sync', {direction:'push', kind})">В Google</button>
          </div>
          <button :disabled="syncBusy" @click="googleAction('disconnect')">Отключить Google</button>
        </template>
        <button v-else-if="google?.configured" class="account-primary" :disabled="syncBusy" @click="googleAction('connect')">Подключить аккаунт Google</button>
        <p v-if="syncBusy" role="status">Обмен выполняется…</p>
        <p v-if="message" class="google-feedback" role="status">{{ message }}</p>
      </section>
    </div>
  </template>
</template>

<style scoped>
.account-screen,.account-overlay{display:grid;place-items:center;padding:1rem}
.account-screen{min-height:100vh}
.account-overlay{position:fixed;inset:0;z-index:1000;background:#17131fb3}
.account-card{position:relative;display:grid;gap:.9rem;width:min(100%,30rem);padding:1.5rem;border-radius:1rem;background:#fff;color:#211b28;box-shadow:0 1rem 3rem #211b2833}
.account-card h1,.account-card h2,.account-card p{margin:0}
.account-card label{display:grid;gap:.3rem}
.account-card input,.account-card button{padding:.65rem .85rem;border:1px solid #d8d2dd;border-radius:.5rem;background:#fff;color:inherit}
.account-card .account-primary{background:#25202d;color:#fff;border-color:#25202d}
.account-card .account-close{position:absolute;right:.75rem;top:.75rem;padding:.2rem .6rem}
.google-actions{display:flex;align-items:center;gap:.5rem;flex-wrap:wrap}
.google-actions strong{margin-right:auto}
.google-import{display:grid;gap:.9rem}
.google-import fieldset{display:grid;gap:.5rem;margin:0;padding:.55rem .75rem .75rem;border:1px solid #d8d2dd;border-radius:.5rem}
.account-card .google-import-choice{display:flex;align-items:center;gap:.55rem;padding:.25rem 0}
.google-import-choice input{width:1rem;height:1rem;margin:0}
.google-feedback{white-space:pre-line}
</style>
