import { addDays, dateKey, fromKey } from '../../shared/calendar.js'

export function todoCalendarItems(todos) {
  return todos.filter(todo => todo.scheduled_date).map(todo => {
    const start = todo.scheduled_at || todo.scheduled_date + 'T00:00:00'
    const end = todo.scheduled_at ? new Date(+new Date(start) + 30 * 60000).toISOString()
      : dateKey(addDays(fromKey(todo.scheduled_date), 1)) + 'T00:00:00'
    return {...todo, id:'todo:' + todo.id, todo_id:todo.id, entity:'todo',
      start, end, is_all_day:!todo.scheduled_at, recurrence:null, is_fixed:false}
  })
}
export function todoScheduleLabel(todo) {
  if (!todo.scheduled_date) return 'Без даты'
  const day = todo.scheduled_at ? new Date(todo.scheduled_at) : fromKey(todo.scheduled_date)
  return day.toLocaleDateString('ru-RU',{day:'numeric',month:'short'}) +
    (todo.scheduled_at ? ' · ' + day.toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'}) : '')
}
