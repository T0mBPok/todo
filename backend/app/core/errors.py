import re
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException
from app.core.request_logging import request_id

DEFAULTS = {
    400:'Не удалось выполнить действие. Проверьте введённые данные.',
    401:'Войдите в аккаунт.', 403:'Для этого действия недостаточно доступа.',
    404:'Запись не найдена. Возможно, её уже удалили.',
    405:'Это действие сейчас недоступно.', 409:'Данные изменились. Обновите список и повторите действие.',
    413:'Запись слишком большая. Сократите её и попробуйте снова.',
    422:'Проверьте заполненные поля.', 429:'Слишком много запросов. Подождите немного и повторите.',
    500:'Не удалось выполнить действие из-за ошибки сервиса. Попробуйте позже.',
    502:'Сервис временно не отвечает. Попробуйте позже.',
    503:'Сервис временно недоступен. Попробуйте позже.',
    504:'Обработка заняла слишком много времени. Попробуйте ещё раз.',
}

def public_detail(status, detail):
    if isinstance(detail, str):
        detail = re.sub(r'(?:Код запроса|request[ _-]?id|trace[ _-]?id)\s*[:=]\s*[^\s.,;]+[.]?', '', detail, flags=re.I).strip()
        if re.search('[а-яё]', detail, re.I) and len(detail) <= 1200 and not re.search(
                r'traceback|sqlalchemy|psycopg|sk-or-|GOCSPX-|[a-f0-9]{32,}', detail, re.I):
            return detail
    return DEFAULTS.get(status, 'Не удалось выполнить действие. Попробуйте ещё раз.')

def install_error_handlers(app):
    @app.exception_handler(HTTPException)
    async def handled_error(request, error):
        return JSONResponse({'detail':public_detail(error.status_code, error.detail)},
                            status_code=error.status_code, headers=error.headers)

    @app.exception_handler(RequestValidationError)
    async def invalid_input(request, error):
        names={'email':'почту','password':'пароль','code':'код из письма','title':'название',
               'start':'дату и время начала','end':'дату и время окончания','text':'текст команды'}
        fields=list(dict.fromkeys(names.get(str(item['loc'][-1])) for item in error.errors()))
        fields=[field for field in fields if field]
        message='Проверьте '+', '.join(fields[:3])+'.' if fields else 'Проверьте формат и длину введённых данных.'
        return JSONResponse({'detail':message},status_code=422)

    @app.exception_handler(Exception)
    async def internal_error(request, error):
        return JSONResponse({'detail':DEFAULTS[500]},status_code=500,
            headers={'X-Request-ID':getattr(request.state,'request_id',request_id.get()),'Cache-Control':'no-store'})
