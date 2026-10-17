import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

const source = (await readFile(new URL('../src/features/voice/useVoiceInput.js', import.meta.url), 'utf8'))
  .replace("import { ref, onUnmounted } from 'vue'", "const ref = value => ({ value }); const onUnmounted = fn => {}")
const { useVoiceInput } = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'))
function setup({ denied = false } = {}) {
  let stopped = 0, recorder, completed = 0, error = '', posted = 0
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: { mediaDevices: {
    getUserMedia: async () => {
      if (denied) throw Object.assign(new Error('denied'), { name: 'NotAllowedError' })
      return { getTracks: () => [{ stop: () => { stopped++ } }] }
    }
  } } })
  class Recorder {
    static isTypeSupported() { return true }
    constructor() { recorder = this; this.mimeType = 'audio/webm'; this.state = 'inactive' }
    start() { this.state = 'recording' }
    stop() {
      this.state = 'inactive'
      this.ondataavailable({ data: new Blob(['test audio']) })
      this.finished = this.onstop()
    }
  }
  globalThis.window = { MediaRecorder: Recorder }
  globalThis.MediaRecorder = Recorder
  globalThis.fetch = async (url, options) => {
    posted++; assert.equal(url, '/api/voice/transcribe'); assert.ok(options.body instanceof Blob)
    return { ok: true, json: async () => ({ text: 'Завтра встреча' }) }
  }
  const text = { value: '' }
  const hook = useVoiceInput({ text, onComplete: () => { completed++ }, onError: value => { error = value } })
  return { hook, text, recorder: () => recorder, status: () => ({ stopped, completed, error, posted }) }
}

test('records audio, transcribes and triggers planning once', async () => {
  const state = setup()
  await state.hook.toggle(); assert.equal(state.hook.listening.value, true)
  await state.hook.toggle(); await state.recorder().finished
  assert.equal(state.text.value, 'Завтра встреча')
  assert.deepEqual(state.status(), { stopped: 1, completed: 1, error: '', posted: 1 })
  assert.equal(state.hook.processing.value, false)
})

test('permission denial produces actionable error and resets state', async () => {
  const state = setup({ denied: true })
  await state.hook.toggle()
  assert.match(state.status().error, /Доступ к микрофону запрещён/)
  assert.equal(state.hook.listening.value, false)
  assert.equal(state.hook.starting.value, false)
  assert.equal(state.status().posted, 0)
})

test('cancelled recording does not upload or create tasks', async () => {
  const state = setup()
  await state.hook.toggle(); state.hook.cancel(); await state.recorder().finished
  assert.equal(state.status().posted, 0)
  assert.equal(state.status().completed, 0)
  assert.equal(state.status().stopped, 1)
})

test('new recording replaces a failed command instead of accumulating old transcripts',async()=>{
  const state=setup()
  state.text.value='Старая неудачная команда: убрать всё кроме пары'
  await state.hook.toggle();await state.hook.toggle();await state.recorder().finished
  assert.equal(state.text.value,'Завтра встреча')
  assert.equal(state.status().completed,1)
})
