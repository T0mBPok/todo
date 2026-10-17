from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool
from app.voice.schemas import Transcript
from app.voice.service import transcribe_audio

router = APIRouter(prefix='/voice', tags=['voice'])
MAX_AUDIO_BYTES = 12 * 1024 * 1024

@router.post('/transcribe', response_model=Transcript)
async def transcribe(request: Request):
    mime = request.headers.get('content-type', '').split(';')[0]
    if not mime.startswith('audio/') and mime != 'video/webm':
        raise HTTPException(415, 'Ожидается аудиозапись.')
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > MAX_AUDIO_BYTES:
            raise HTTPException(413, 'Запись слишком большая. Запишите не больше 90 секунд.')
    if not data:
        raise HTTPException(422, 'Получена пустая запись.')
    return await run_in_threadpool(transcribe_audio, bytes(data))
