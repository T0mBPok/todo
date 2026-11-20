<script setup>
import { errorMessage } from './shared/errors.js'
import {nextTick, onMounted, onUnmounted, ref, watch} from 'vue'
import TodoApp from './entities/todos/TodoApp.vue'
import CalendarApp from './CalendarApp.vue'
import {request} from './shared/api.js'
import PasswordInput from './shared/PasswordInput.vue'

const globalError = ref('')
function showGlobalError(event) { globalError.value = event.detail }
onMounted(() => window.addEventListener('impulse:error', showGlobalError))
onUnmounted(() => window.removeEventListener('impulse:error', showGlobalError))
const mode = ref('calendar')
const user = ref(null)
const ready = ref(false)
const registration = ref(false)
const recovery = ref(false)
const passwordAgain = ref('')
const recoveryNotice = ref('')
const accountOpen = ref(false)
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
const googleConflicts = ref([])
const syncBusy = ref(false)
const message = ref('')
const revision = ref(0)

async function loadUser() {
  error.value = ''
  try {
    user.value = await request('/auth/me')
  } catch (e) {
    if (e.status !== 401) error.value = errorMessage(e)
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
      await openGoogle(connected ? '' : 'Google не подключён. Проверьте разрешения и попробуйте ещё раз.')
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
    error.value = errorMessage(e)
  } finally {
    busy.value = false
  }
}

async function recoverPassword() {
  busy.value = true
  error.value = ''
  verificationNotice.value = ''
  try {
    if (!pendingEmail.value) {
      pendingEmail.value = await request('/auth/request-password-reset', 'POST', { email: email.value })
      code.value = ''
    } else {
      if (password.value !== passwordAgain.value) {
        error.value = 'Пароли не совпадают.'
        return
      }
      await request('/auth/reset-password', 'POST', {
        challenge: pendingEmail.value.challenge, code: code.value, password: password.value
      })
      recovery.value = false
      pendingEmail.value = null
      password.value = ''
      passwordAgain.value = ''
      code.value = ''
      recoveryNotice.value = 'Пароль обновлён. Войдите с новым паролем.'
    }
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    busy.value = false
  }
}

function openRecovery() {
  recovery.value = true
  registration.value = false
  password.value = ''
  passwordAgain.value = ''
  pendingEmail.value = null
  error.value = ''
  recoveryNotice.value = ''
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
    error.value = errorMessage(e)
  } finally {
    busy.value = false
  }
}

async function resendEmail() {
  busy.value = true
  error.value = ''
  verificationNotice.value = ''
  try {
    await request(recovery.value ? '/auth/resend-password-reset' : '/auth/resend-email', 'POST', {challenge: pendingEmail.value.challenge})
    code.value = ''
    verificationNotice.value = 'Отправили новый код. Используйте последнее письмо.'
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    busy.value = false
  }
}

function backToAccountForm() {
  pendingEmail.value = null
  code.value = ''
  password.value = ''
  passwordAgain.value = ''
  recovery.value = false
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
    error.value = errorMessage(e)
  }
}

async function openGoogle(notice = '') {
  googleOpen.value = true
  google.value = null
  googleConflicts.value = []
  message.value = notice
  try {
    google.value = await request('/google/status')
    if (google.value.conflicts) googleConflicts.value = await request('/google/conflicts')
  } catch (e) {
    message.value = errorMessage(e)
  }
  await nextTick()
  googleDialog.value?.focus()
}

function closeGoogle() {
  if (syncBusy.value) return
  googleOpen.value = false
  nextTick(() => googleTrigger.value?.focus())
}

function syncSummary(result) {
  return 'Обновлено: ' + result.changed + '. Пропущено: ' + result.skipped +
    '. Конфликтов: ' + result.conflicts + '.' +
    (result.partial ? ' Обработана часть записей. Повторите обмен, чтобы продолжить.' : '')
}

let googlePollTimer, googlePollBusy=false, lastGoogleSync=null
async function pollGoogleStatus() {
  if (!user.value || googlePollBusy || syncBusy.value) return
  googlePollBusy=true
  try {
    const state=await request('/google/status')
    if (lastGoogleSync && state.last_synced_at && lastGoogleSync!==state.last_synced_at) revision.value++
    lastGoogleSync=state.last_synced_at
    google.value=state
    if (googleOpen.value) googleConflicts.value=state.conflicts ? await request('/google/conflicts') : []
  } catch (error) {
    if (googleOpen.value) message.value=errorMessage(error)
  } finally { googlePollBusy=false }
}
function resumeGoogleStatus() { if (document.visibilityState==='visible') pollGoogleStatus() }
watch(user,value=>{ if (value) pollGoogleStatus(); else { google.value=null;lastGoogleSync=null } })
onMounted(()=>{
  googlePollTimer=setInterval(pollGoogleStatus,30000)
  document.addEventListener('visibilitychange',resumeGoogleStatus)
})
onUnmounted(()=>{clearInterval(googlePollTimer);document.removeEventListener('visibilitychange',resumeGoogleStatus)})
async function toggleGoogleAuto(enabled) {
  syncBusy.value=true;message.value=''
  try {
    google.value=await request('/google/auto-sync','POST',{enabled})
    message.value=enabled?'Автосинхронизация включена. Первый обмен начнётся автоматически.':'Автосинхронизация приостановлена.'
  } catch (error) { message.value=errorMessage(error) }
  finally {syncBusy.value=false}
}
async function syncGoogleNow() {
  syncBusy.value=true
  try {message.value=(await request('/google/sync-now','POST')).note}
  catch(error){message.value=errorMessage(error)}
  finally{syncBusy.value=false}
}
async function resolveGoogleConflict(item,source) {
  syncBusy.value=true;message.value=''
  try {
    message.value=(await request('/google/resolve','POST',{local_id:item.local_id,kind:item.kind,source})).note
    googleConflicts.value=await request('/google/conflicts')
    google.value=await request('/google/status')
    revision.value++
  } catch(error) { message.value=errorMessage(error) }
  finally {syncBusy.value=false}
}
function googleSyncTime(value) { return new Date(value).toLocaleString('ru-RU',{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'}) }

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
    message.value = errorMessage(e)
    if (payload?.direction === 'pull') revision.value++
  } finally {
    syncBusy.value = false
  }
}
</script>

<template>
  <div v-if="globalError" class="app-error-toast" role="alert"><span>{{ globalError }}</span><button type="button" aria-label="Закрыть сообщение об ошибке" @click="globalError=''">×</button></div>
  <main v-if="!ready" class="account-screen" aria-busy="true">Загружаем приложение…</main>
  <main v-else-if="!user" class="account-screen">
    <form v-if="recovery" class="account-card" @submit.prevent="recoverPassword">
      <div class="impulse-brand"><span class="impulse-mark" aria-hidden="true">↯</span><span>Импульс</span></div>
      <h1>{{ pendingEmail ? 'Новый пароль' : 'Восстановить доступ' }}</h1>
      <p v-if="pendingEmail">Если для {{ pendingEmail.email }} есть подтверждённый аккаунт, на почту придёт код. Он действует 10 минут.</p>
      <p v-else>Пришлём код на почту вашего аккаунта.</p>
      <label v-if="!pendingEmail">Почта<input v-model.trim="email" type="email" autocomplete="username" maxlength="254" required></label>
      <template v-else>
        <label>Код из письма<input v-model.trim="code" inputmode="numeric" pattern="[0-9]{8}" maxlength="8" autocomplete="one-time-code" required></label>
        <label>Новый пароль<PasswordInput v-model="password" minlength="15" maxlength="128" autocomplete="new-password" required /></label>
        <label>Повторите пароль<PasswordInput v-model="passwordAgain" minlength="15" maxlength="128" autocomplete="new-password" required /></label>
        <small>Минимум 15 символов.</small>
      </template>
      <p v-if="error" role="alert">{{ error }}</p>
      <p v-if="verificationNotice" role="status">{{ verificationNotice }}</p>
      <button class="account-primary" :disabled="busy">{{ busy ? 'Подождите…' : pendingEmail ? 'Сохранить пароль' : 'Получить код' }}</button>
      <button v-if="pendingEmail" type="button" :disabled="busy" @click="resendEmail">Отправить код ещё раз</button>
      <button type="button" :disabled="busy" @click="backToAccountForm">Вернуться ко входу</button>
    </form>
    <form v-else-if="pendingEmail" class="account-card" @submit.prevent="confirmEmail">
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
      <label>Пароль<PasswordInput v-model="password" :minlength="registration ? 15 : 1"
        maxlength="128" :autocomplete="registration ? 'new-password' : 'current-password'" :key="registration" required /></label>
      <small v-if="registration">Минимум 15 символов.</small>
      <p v-if="error" role="alert">{{ error }}</p>
      <p v-if="recoveryNotice" role="status">{{ recoveryNotice }}</p>
      <button v-if="!registration" type="button" class="forgot-password" :disabled="busy" @click="openRecovery">Забыли пароль?</button>
      <button class="account-primary" type="submit" :disabled="busy">{{ busy ? 'Подождите…' : registration ? 'Зарегистрироваться' : 'Войти' }}</button>
      <button type="button" :disabled="busy" @click="registration = !registration; error = ''">
        {{ registration ? 'Уже есть аккаунт' : 'Создать аккаунт' }}
      </button>
    </form>
  </main>
  <template v-else>
    <header class="mode-switch workspace-header" :class="{'has-calendar':mode==='calendar'}" :inert="googleOpen">
      <div class="impulse-brand"><span class="impulse-mark" aria-hidden="true">↯</span><span>Импульс<small>ЛИЧНЫЙ ПЛАНИРОВЩИК</small></span></div>
      <div id="calendar-toolbar-host" v-show="mode==='calendar'" class="calendar-toolbar-host"></div>
      <nav class="section-tabs" aria-label="Раздел приложения">
        <button :class="{active:mode==='todos'}" @click="mode='todos'">✓ Задачи</button>
        <button :class="{active:mode==='calendar'}" @click="mode='calendar'">▦ Календарь</button>
      </nav>
      <div class="account-menu" @focusout="!$event.currentTarget.contains($event.relatedTarget) && (accountOpen=false)">
        <button class="account-avatar" :aria-expanded="accountOpen" aria-label="Аккаунт и подключения" @click="accountOpen=!accountOpen">{{ user.email[0].toUpperCase() }}</button>
        <div v-if="accountOpen" class="account-popover" @keydown.esc="accountOpen=false">
          <span>{{ user.email }}</span>
          <button ref="googleTrigger" @click="accountOpen=false;openGoogle()">Подключение Google</button>
          <button @click="accountOpen=false;logout()">Выйти из аккаунта</button>
        </div>
      </div>
    </header>
    <p v-if="error" role="alert">{{ error }}</p>
    <div class="mode-content" :inert="googleOpen"><TodoApp v-if="mode==='todos'" :refresh-token="revision"/><CalendarApp v-else :refresh-token="revision"/></div>
    <div v-if="googleOpen" class="account-overlay" @click.self="closeGoogle">
      <section ref="googleDialog" class="account-card" role="dialog" aria-modal="true"
        aria-labelledby="google-dialog-title" tabindex="-1" @keydown.esc="closeGoogle">
        <button class="account-close" aria-label="Закрыть" :disabled="syncBusy" @click="closeGoogle">×</button>
        <h2 id="google-dialog-title">Обмен с Google</h2>
        <p v-if="google && !google.configured">Администратор ещё не настроил Google OAuth.</p>
        <template v-else-if="google?.connected">
          <p>Основной календарь Google и список Google Tasks по умолчанию.</p>
          <label class="google-auto-switch"><input type="checkbox" :checked="google.auto_sync" :disabled="syncBusy" @change="toggleGoogleAuto($event.target.checked)"><span>Автоматическая синхронизация<small>Создание, изменения и удаления в обе стороны. Работает в фоне, даже когда приложение закрыто.</small></span></label>
          <div class="google-sync-state" role="status">
            <strong>{{ google.auto_sync ? 'Обмениваемся автоматически, примерно раз в минуту' : 'Автосинхронизация приостановлена' }}</strong>
            <span v-if="google.last_synced_at">Последний обмен: {{ googleSyncTime(google.last_synced_at) }}</span>
            <span v-else-if="google.auto_sync">Ожидаем первый обмен…</span>
            <span v-if="google.partial">Переносим оставшиеся записи следующей порцией.</span>
          </div>
          <p v-if="google.sync_error" role="alert" class="google-sync-error">{{ google.sync_error }}</p>
          <button v-if="google.auto_sync" :disabled="syncBusy" @click="syncGoogleNow">Синхронизировать сейчас</button>
          <section v-if="googleConflicts.length" class="google-conflicts">
            <h3>Нужно выбрать версию</h3><p>Эти записи изменились в обоих приложениях. Выберите, какую версию оставить.</p>
            <article v-for="item in googleConflicts" :key="item.kind+item.local_id">
              <strong>{{ item.local?.title || item.remote?.title || 'Удалённая запись' }}</strong>
              <div v-for="[source, label, version] in [['local','Импульс',item.local],['remote','Google',item.remote]]" :key="source" class="google-conflict-version">
                <span>{{ label }}: {{ version ? version.title : 'Запись удалена' }}<small v-if="version?.start">{{ googleSyncTime(version.start) }} — {{ googleSyncTime(version.end) }}</small></span>
                <button :disabled="syncBusy" @click="resolveGoogleConflict(item,source)">{{ version ? 'Оставить эту версию' : 'Подтвердить удаление' }}</button>
              </div>
            </article>
          </section>
          <button :disabled="syncBusy" @click="googleAction('disconnect')">Отключить Google</button>
        </template>
        <p v-else-if="google?.configured">После подключения включится автоматическая синхронизация событий и задач в обе стороны.</p>
        <button v-if="google?.configured && !google.connected" class="account-primary" :disabled="syncBusy" @click="googleAction('connect')">Подключить аккаунт Google</button>
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
