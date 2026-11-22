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


export function todoDisplayTitle(todo) {
  let title=todo.title||''
  if(!todo.scheduled_date)return title
  const day=Number(todo.scheduled_date.slice(8,10))
  const months=['января','февраля','марта','апреля','мая','июня','июля','августа','сентября','октября','ноября','декабря']
  const month=months[Number(todo.scheduled_date.slice(5,7))-1]
  const clock='(?:\\d{1,2}(?::\\d{2})?|час|шесть|шести|семь|семи|восемь|восьми|девять|девяти|десять|десяти|одиннадцать|одиннадцати|двенадцать|двенадцати)\\s*(?:час(?:а|ов)?\\s*)?(?:утра|дня|вечера|ночи)?'
  const dateSuffix=new RegExp('\\s+(?:на\\s+)?'+day+'(?:-го|-е)?\\s+(?:'+month+'|числ[ао])(?:\\s+\\d{4}(?:\\s+года)?)?(?:\\s+(?:в|на)\\s+'+clock+')?[.!]?$', 'i')
  const match=title.match(dateSuffix)
  if(match){const prefix=title.slice(0,match.index).trim();if(prefix&&!/(?:^|\s)за$/i.test(prefix))title=prefix}
  if(todo.scheduled_at){const prefix=title.replace(new RegExp('\\s+(?:в|на)\\s+'+clock+'[.!]?$', 'i'),'').trim();if(prefix)title=prefix}
  return title
}
