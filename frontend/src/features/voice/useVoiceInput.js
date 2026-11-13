import { ref, onUnmounted } from 'vue'
import { readApiResponse } from '../../shared/api'

export function useVoiceInput({ text, onComplete, onError }) {
  const supported = !!(navigator.mediaDevices?.getUserMedia && window.MediaRecorder)
  const listening = ref(false), processing = ref(false), starting = ref(false)
  const audioUrl = ref(''), rawTranscript = ref(''), engineName = ref(''), elapsed = ref(0), recordSeconds = ref(0)
  let clock, startedAt
  let recorder, stream, timer, chunks = [], disposed = false, cancelled = false, request
  function release() {
    clearTimeout(timer); clearInterval(clock)
    stream?.getTracks().forEach(track => track.stop())
    stream = null; listening.value = false
  }
  async function finish() {
    const mime = recorder?.mimeType || 'audio/webm'
    release()
    if (disposed || cancelled) return
    processing.value = true
    request = new AbortController()
    try {
      const audio = new Blob(chunks, { type: mime })
      if (audioUrl.value) URL.revokeObjectURL(audioUrl.value)
      audioUrl.value = URL.createObjectURL(audio)
      if (!audio.size) throw new Error('Микрофон вернул пустую запись. Попробуйте ещё раз.')
      const response = await fetch('/api/voice/transcribe', {
        method: 'POST', body: audio, headers: { 'Content-Type': mime }, signal: request.signal
      })
      const result = await readApiResponse(response, 'Ошибка распознавания аудио.')
      if (disposed || cancelled) return
      rawTranscript.value = result.text
      engineName.value = result.engine || 'Локальный движок'
      elapsed.value = result.seconds || 0
      // Each recording is a complete command or answer, never an implicit append.
      text.value = result.text.trim().slice(0,6000)
      processing.value = false
      await onComplete()
    } catch (error) {
      if (!disposed && !cancelled) onError(error.name === 'TypeError' ? 'Нет связи с сервером распознавания. Попробуйте ещё раз.' : error.message)
    } finally { processing.value = false }
  }
  async function toggle() {
    if (listening.value) { if (recorder?.state === 'recording') recorder.stop(); return }
    if (starting.value || processing.value || !supported) return
    starting.value = true; cancelled = false; chunks = []
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true }, video: false })
      if (disposed || cancelled) { release(); return }
      const mimeType = ['audio/webm;codecs=opus','audio/webm','audio/mp4','audio/ogg;codecs=opus'].find(type => MediaRecorder.isTypeSupported(type))
      recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined)
      recorder.ondataavailable = event => { if (event.data.size) chunks.push(event.data) }
      recorder.onstop = finish
      recorder.onerror = () => { cancelled = true; release(); onError('Не удалось записать звук. Проверьте микрофон.') }
      recorder.start(250); listening.value = true; recordSeconds.value = 0; startedAt = Date.now()
      clock = setInterval(() => { recordSeconds.value = Math.floor((Date.now() - startedAt) / 1000) }, 250)
      timer = setTimeout(() => { if (recorder?.state === 'recording') recorder.stop() }, 90000)
    } catch (error) {
      release()
      const messages = {
        NotAllowedError: 'Доступ к микрофону запрещён. Разрешите микрофон для этого сайта в настройках браузера.',
        NotFoundError: 'Микрофон не найден. Подключите его и повторите запись.',
        NotReadableError: 'Не удаётся открыть микрофон. Проверьте, не занят ли он другим приложением.'
      }
      onError(messages[error.name] || 'Не удалось запустить микрофон: ' + error.message)
    } finally { starting.value = false }
  }
  function cancel() {
    cancelled = true; request?.abort()
    if (recorder?.state === 'recording') recorder.stop()
    release()
  }
  onUnmounted(() => { disposed = true; cancel(); if (audioUrl.value) URL.revokeObjectURL(audioUrl.value) })
  return { supported, listening, processing, starting, toggle, cancel, audioUrl, rawTranscript, engineName, elapsed, recordSeconds }
}
