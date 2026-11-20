const defaults = {
  400:'Не удалось выполнить действие. Проверьте введённые данные.',
  401:'Сессия завершилась. Войдите в аккаунт ещё раз.',
  403:'Для этого действия недостаточно доступа.',
  404:'Запись не найдена. Возможно, её уже удалили. Обновите календарь.',
  405:'Это действие сейчас недоступно. Обновите страницу.',
  408:'Ответ не пришёл вовремя. Попробуйте ещё раз.',
  409:'Данные успели измениться. Обновите список и повторите действие.',
  410:'Срок действия истёк. Начните действие заново.',
  413:'Запись слишком большая. Сократите её и попробуйте снова.',
  415:'Этот формат записи не поддерживается. Запишите звук ещё раз.',
  422:'Проверьте название, дату, время и остальные заполненные поля.',
  429:'Слишком много запросов. Подождите немного и повторите.',
  500:'Не удалось выполнить действие из-за ошибки сервиса. Попробуйте позже.',
  502:'Сервис временно не отвечает. Попробуйте ещё раз чуть позже.',
  503:'Сервис временно недоступен. Попробуйте позже.',
  504:'Обработка заняла слишком много времени. Повторите запрос или разделите его на части.'
}
export function publicMessage(value, status, fallback = 'Не удалось выполнить действие. Попробуйте ещё раз.') {
  const message = typeof value === 'string' ? value
    .replace(/(?:Код запроса|request[ _-]?id|trace[ _-]?id|correlation[ _-]?id)\s*[:=]\s*[^\s.,;]+[.]?/gi, '').trim() : ''
  if (message && /[а-яё]/i.test(message) && message.length <= 1200 &&
    !/traceback|stack trace|sqlalchemy|psycopg|\bat [\w.]+\s*\(|\b(?:SELECT|INSERT|UPDATE)\b|sk-or-|GOCSPX-|[a-f0-9]{32,}/i.test(message)) return message
  return defaults[status] || fallback
}
export class AppError extends Error {
  constructor(message, status = 0) { super(message); this.name='AppError'; this.status=status; this.detail=message }
}
export function errorMessage(error, fallback = 'Что-то пошло не так. Попробуйте повторить действие.') {
  if (error?.name === 'AbortError') return 'Действие отменено. Можно попробовать ещё раз.'
  if (error instanceof TypeError) return 'Не удалось связаться с сервисом. Проверьте интернет и попробуйте ещё раз.'
  if (error instanceof RangeError || error instanceof SyntaxError) return fallback
  return publicMessage(error?.message, error?.status, fallback)
}
export function installErrorHandlers(app, target = window) {
  const report = error => target.dispatchEvent(new CustomEvent('impulse:error', {detail:errorMessage(error)}))
  app.config.errorHandler = report
  target.addEventListener('unhandledrejection', event => {
    if (event.reason?.name === 'AbortError') { event.preventDefault(); return }
    report(event.reason); event.preventDefault()
  })
  target.addEventListener('error', event => { if (event.error) report(event.error) })
}
