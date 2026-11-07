"""Shared transport. All domain modules keep their existing schemas and validation."""
import json as jsonlib
from urllib.parse import urlsplit
import httpx
from fastapi import HTTPException
from app.core import config

def ai_post(url,*,timeout,json):
    if config.AI_PROVIDER=='ollama':
        return httpx.post(url,timeout=timeout,json=json)
    official=config.AI_PROVIDER=='dashscope'
    provider='Alibaba Cloud Model Studio' if official else 'OpenRouter'
    key=config.DASHSCOPE_API_KEY if official else config.OPENROUTER_API_KEY
    if not key:
        setting='DASHSCOPE_API_KEY' if official else 'OPENROUTER_API_KEY'
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
    if not official and config.OPENROUTER_RESPONSE_FORMAT=='json_schema':
        response_format={'type':'json_schema','json_schema':{'name':'calendar_result','strict':True,'schema':schema}}
    else:
        response_format={'type':'json_object'}
        messages.insert(0,{'role':'system','content':'Верни только JSON, строго соответствующий следующей JSON Schema. Никакого Markdown или текста вне JSON: '+jsonlib.dumps(schema,ensure_ascii=False)})
    payload={'model':config.ai_model(),'messages':messages,'stream':False,
        'temperature':json.get('options',{}).get('temperature',0),
        'max_tokens':json.get('options',{}).get('num_predict',2600),
        'response_format':response_format}
    if official:payload['enable_thinking']=False
    else:
        payload['provider'] = {'require_parameters': True}
        if payload['model'] == 'nvidia/nemotron-3.5-super-vl:free' and json.get('think') is False:
            payload['reasoning'] = {'enabled': False}
        # Cloud requests should fail promptly when a free endpoint stalls.
        timeout = httpx.Timeout(min(timeout, 12), connect=min(timeout, 3))
    try:
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
        choice=value['choices'][0];content=choice['message']['content']
        if not isinstance(content,str) or not content.strip():raise HTTPException(502,f'{provider} вернул пустой ответ.')
        return httpx.Response(200,request=httpx.Request('POST','http://ai.internal/result'),json={'message':{'content':content},'done_reason':choice.get('finish_reason','stop')})
    except httpx.TimeoutException:
        raise HTTPException(504,f'{provider} не ответил вовремя. Попробуйте сократить запрос.') from None
    except httpx.RequestError:
        raise HTTPException(503,f'Нет связи с {provider}. Проверьте доступ сервера в интернет.') from None
    except (ValueError,KeyError,IndexError,TypeError):
        raise HTTPException(502,f'{provider} вернул некорректный ответ. Календарь не изменён.') from None
