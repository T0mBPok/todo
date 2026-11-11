"""Shared transport. All domain modules keep their existing schemas and validation."""
import json as jsonlib
from urllib.parse import urlsplit
import httpx
from fastapi import HTTPException
from app.core import config, gigachat

def ai_post(url,*,timeout,json):
    if config.AI_PROVIDER=='ollama':
        return httpx.post(url,timeout=timeout,json=json)
    official=config.AI_PROVIDER=='dashscope'
    is_gigachat = config.AI_PROVIDER == 'gigachat'
    provider, setting = {
        'dashscope': ('Alibaba Cloud Model Studio', 'DASHSCOPE_API_KEY'),
        'gigachat': ('GigaChat', 'GIGACHAT_AUTH_KEY'),
        'openrouter': ('OpenRouter', 'OPENROUTER_API_KEY'),
    }[config.AI_PROVIDER]
    key = getattr(config, setting)
    if not key:
        raise HTTPException(503,f'Для {provider} не задан {setting} в настройках бэкенда.')
    endpoint='https://openrouter.ai/api/v1/chat/completions'
    if official:
        address=urlsplit(config.DASHSCOPE_BASE_URL)
        host=address.hostname or ''
        if (address.scheme!='https' or address.netloc!=host or address.query or address.fragment
                or address.path!='/compatible-mode/v1' or not (host in {
                    'dashscope-intl.aliyuncs.com','dashscope.aliyuncs.com','dashscope-us.aliyuncs.com',
                    'cn-hongkong.dashscope.aliyuncs.com'} or host.endswith('.maas.aliyuncs.com'))):
            raise HTTPException(503,'DASHSCOPE_BASE_URL должен указывать на официальный HTTPS API Model Studio.')
        endpoint=config.DASHSCOPE_BASE_URL+'/chat/completions'
    messages=[dict(message) for message in json['messages']]
    schema=json.get('format',{})
    if is_gigachat:
        # Native constrained decoding stalls on the application's nested schemas.
        required = ', '.join(schema.get('required', ()))
        schema_line = 'Схема JSON (только правила формата): ' + jsonlib.dumps(schema, ensure_ascii=False, separators=(',', ':'))
        instruction = ('Верни только объект с результатом, без Markdown. Не копируй схему и её служебные поля. '
                       'Обязательные поля верхнего уровня: ' + required + '. '
                       'Если для текстового пояснения нечего добавить, передай пустую строку.')
        if messages and messages[0]['role'] == 'system':
            messages[0]['content'] = '\n'.join((schema_line, messages[0]['content'], instruction))
        else:
            messages.insert(0, {'role': 'system', 'content': schema_line + '\n' + instruction})
        response_format = None
    elif not official and config.OPENROUTER_RESPONSE_FORMAT=='json_schema':
        response_format={'type':'json_schema','json_schema':{'name':'calendar_result','strict':True,'schema':schema}}
    else:
        response_format={'type':'json_object'}
        messages.insert(0,{'role':'system','content':'Верни только JSON, строго соответствующий следующей JSON Schema. Никакого Markdown или текста вне JSON: '+jsonlib.dumps(schema,ensure_ascii=False)})
    payload={'model':config.ai_model(),'messages':messages,'stream':False,
        'temperature':json.get('options',{}).get('temperature',0),
        'max_tokens':json.get('options',{}).get('num_predict',2600)}
    if response_format is not None:
        payload['response_format'] = response_format
    if is_gigachat:
        timeout = httpx.Timeout(min(timeout, 15), connect=min(timeout, 4))
    elif official:payload['enable_thinking']=False
    else:
        payload['provider'] = {'require_parameters': True}
        if payload['model'] == 'nvidia/nemotron-3.5-super-vl:free' and json.get('think') is False:
            payload['reasoning'] = {'enabled': False}
        # Cloud requests should fail promptly when a free endpoint stalls.
        timeout = httpx.Timeout(min(timeout, 12), connect=min(timeout, 3))
    try:
        if is_gigachat:
            response = gigachat.post(payload, timeout)
        else:
            response=httpx.post(endpoint,timeout=timeout,
                headers={'Authorization':'Bearer '+key},json=payload)
        if official and response.status_code == 403:
            try:
                body=response.json()
                error=body.get('error',body)
                quota_only=error.get('code')=='AllocationQuota.FreeTierOnly'
            except (ValueError,AttributeError):
                quota_only=False
            if quota_only:
                raise HTTPException(503,'Бесплатная квота Qwen исчерпана или недоступна. Переключитесь на локальный Ollama.')
        if response.status_code in (401,403):raise HTTPException(503,f'{provider} отклонил ключ или доступ к модели. Проверьте серверные настройки.')
        if response.status_code==402:raise HTTPException(503,f'{provider}: недостаточно средств или недоступен бесплатный тариф выбранной модели.')
        if response.status_code==429:raise HTTPException(429,f'Достигнут лимит {provider}. Подождите или проверьте дневную квоту.')
        if response.status_code in (400,404):raise HTTPException(503,f'Модель {provider} недоступна или не поддерживает выбранный формат JSON. Проверьте модель и регион API.')
        if response.is_error:raise HTTPException(502,f'Ошибка провайдера {provider}. Повторите запрос позже.')
        value=response.json()
        if value.get('error'):raise HTTPException(502,f'{provider} не завершил запрос. Повторите позже.')
        choices = value.get('choices') or []
        choice = choices[0] if choices else {}
        if is_gigachat and choice.get('finish_reason') == 'blacklist':
            raise HTTPException(422, 'GigaChat отклонил формулировку. Попробуйте сказать иначе.')
        content = choice.get('message', {}).get('content')
        if not isinstance(content,str) or not content.strip():
            if is_gigachat:
                raise HTTPException(502, 'GigaChat не вернул результат. Попробуйте повторить команду.')
            raise HTTPException(502,f'{provider} вернул пустой ответ.')
        if is_gigachat and choice.get('finish_reason') != 'length':
            # GigaChat can emit literal newlines in JSON strings such as shopping lists.
            # Re-encode the parsed value; domain validators still check the actual fields.
            parsed = jsonlib.loads(content, strict=False)
            content = jsonlib.dumps(parsed, ensure_ascii=False, separators=(',', ':'))
        return httpx.Response(200,request=httpx.Request('POST','http://ai.internal/result'),json={'message':{'content':content},'done_reason':choice.get('finish_reason','stop')})
    except httpx.TimeoutException:
        raise HTTPException(504,f'{provider} не ответил вовремя. Попробуйте сократить запрос.') from None
    except httpx.RequestError:
        raise HTTPException(503,f'Нет связи с {provider}. Проверьте доступ сервера в интернет.') from None
    except (ValueError,KeyError,IndexError,TypeError,AttributeError):
        raise HTTPException(502,f'{provider} вернул некорректный ответ. Календарь не изменён.') from None
