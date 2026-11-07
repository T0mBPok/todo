"""Make one opt-in smoke request without calendar or account data."""
import json
from fastapi import HTTPException
import httpx
from app.core import config
from app.core.ai_client import ai_post


def main():
    payload={
        'model':config.ai_model(), 'stream':False, 'think':False,
        'messages':[{'role':'user','content':'Ответь только JSON: {"ok": true}'}],
        'format':{'type':'object','properties':{'ok':{'type':'boolean'}},'required':['ok']},
        'options':{'num_predict':32,'temperature':0},
    }
    try:
        response=ai_post(config.OLLAMA_BASE_URL+'/api/chat',timeout=30,json=payload)
        response.raise_for_status()
        result=json.loads(response.json()['message']['content'])
        if result != {'ok':True}:
            raise ValueError('Unexpected response')
    except HTTPException as error:
        raise SystemExit(error.detail) from None
    except (httpx.HTTPError,ValueError,KeyError,TypeError):
        raise SystemExit('Проверка ИИ не прошла: недоступный или некорректный ответ.') from None
    print(f'Готово: {config.AI_PROVIDER} / {config.ai_model()}')


if __name__=='__main__':
    main()
