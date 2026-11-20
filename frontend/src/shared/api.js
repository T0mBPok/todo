import { AppError, publicMessage } from './errors.js'
export { errorMessage } from './errors.js'

export async function request(path, method = 'GET', body) {
  let response
  try {
    response = await fetch('/api' + path, {
      method, headers: { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body)
    })
  } catch (_) {
    throw new AppError('Не удалось связаться с сервисом. Проверьте интернет и попробуйте ещё раз.')
  }
  return readApiResponse(response)
}
export async function readApiResponse(response, fallback = 'Не удалось выполнить действие. Попробуйте ещё раз.') {
  if (response.status === 204) return null
  if (response.ok) {
    try { return await response.json() }
    catch (_) { throw new AppError('Не удалось прочитать ответ сервиса. Попробуйте ещё раз.', 502) }
  }
  const result = await response.json().catch(() => null)
  throw new AppError(publicMessage(result?.detail, response.status, fallback), response.status)
}
export function localDate(value) {
  const date = new Date(value)
  return new Date(date - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16)
}
export function taskPayload(task) {
  return { is_fixed: !!task.is_fixed, category: task.category || 'important_not_urgent', title: task.title, description: task.description || "", start: new Date(task.start).toISOString(), end: new Date(task.end).toISOString(), recurrence: task.recurrence || (['daily','weekly'].includes(task.repeat) ? {frequency:task.repeat,timezone:Intl.DateTimeFormat().resolvedOptions().timeZone} : null) }
}
