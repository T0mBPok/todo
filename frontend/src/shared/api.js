export async function request(path, method = 'GET', body) {
  const response = await fetch('/api' + path, {
    method, headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body)
  })
  if (response.status === 204) return null
  const result = await response.json()
  if (!response.ok) {
    const error = new Error(typeof result.detail === 'string' ? result.detail : 'Проверьте введённые данные.')
    error.status = response.status
    throw error
  }
  return result
}
export function localDate(value) {
  const date = new Date(value)
  return new Date(date - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16)
}
export function taskPayload(task) {
  return { is_fixed: !!task.is_fixed, category: task.category || 'important_not_urgent', title: task.title, description: task.description || "", start: new Date(task.start).toISOString(), end: new Date(task.end).toISOString(), recurrence: task.recurrence || (['daily','weekly'].includes(task.repeat) ? {frequency:task.repeat,timezone:Intl.DateTimeFormat().resolvedOptions().timeZone} : null) }
}
