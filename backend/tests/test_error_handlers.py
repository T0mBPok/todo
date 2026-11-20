from fastapi import FastAPI,HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel
from app.core.errors import install_error_handlers
from app.core.request_logging import log_request

def test_custom_http_and_validation_errors_do_not_expose_diagnostics():
    api=FastAPI()
    install_error_handlers(api)
    api.middleware('http')(log_request)
    @api.get('/failure')
    def failure():
        raise HTTPException(409,'Событие изменилось. Код запроса: '+ 'a'*32)
    class Input(BaseModel):
        email:str
        password:str
    @api.post('/validate')
    def validate(data:Input):return {}
    with TestClient(api) as client:
        response=client.get('/failure')
        assert response.json()=={'detail':'Событие изменилось.'}
        assert response.headers['x-request-id']
        response=client.post('/validate',json={'email':'private@example.com'})
        assert response.status_code==422
        assert response.json()=={'detail':'Проверьте пароль.'}
        assert 'private' not in response.text
        assert client.get('/missing').json()['detail'].startswith('Запись не найдена')

def test_unexpected_errors_are_generic_and_remain_traceable_in_logs(caplog):
    api=FastAPI()
    install_error_handlers(api)
    api.middleware('http')(log_request)
    @api.get('/failure')
    def failure():raise RuntimeError('private database password')
    with TestClient(api,raise_server_exceptions=False) as client:
        with caplog.at_level('INFO',logger='uvicorn.error'):
            response=client.get('/failure')
        assert response.status_code==500
        assert 'private' not in response.text
        assert 'Код запроса' not in response.text
        assert response.headers['x-request-id'] in caplog.text
        assert 'RuntimeError' in caplog.text
