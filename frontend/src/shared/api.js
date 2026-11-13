export async function request(path, method = 'GET', body) {
  const response = await fetch('/api' + path, {
    method, headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body)
  })
  return readApiResponse(response)
}
export async function readApiResponse(response, fallback = 'Ошибка запроса к серверу.') {
  if (response.status === 204) return null
  if (response.ok) return response.json()
  const result = await response.json().catch(() => null)
  const message = typeof result?.detail === 'string' ? result.detail : fallback
  const id = response.headers.get('X-Request-ID')
  const error = new Error(id ? `${message} Код запроса: ${id}` : message)
  error.status = response.status
  error.detail = message
  throw error
}
export function localDate(value) {
  const date = new Date(value)
  return new Date(date - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16)
}
export function taskPayload(task) {
  return { is_fixed: !!task.is_fixed, category: task.category || 'important_not_urgent', title: task.title, description: task.description || "", start: new Date(task.start).toISOString(), end: new Date(task.end).toISOString(), recurrence: task.recurrence || (['daily','weekly'].includes(task.repeat) ? {frequency:task.repeat,timezone:Intl.DateTimeFormat().resolvedOptions().timeZone} : null) }
}
