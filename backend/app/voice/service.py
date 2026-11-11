from functools import lru_cache
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock
import os
import logging
import av
import httpx
from time import perf_counter
from fastapi import HTTPException

_lock = Lock()

@lru_cache(maxsize=1)
def get_model():
    from faster_whisper import WhisperModel
    return WhisperModel(os.getenv('WHISPER_MODEL_PATH', '/models/whisper-small'),
                        device='cpu', compute_type='int8', cpu_threads=4, local_files_only=True)

def whisper_transcribe(audio: bytes):
    with TemporaryDirectory() as directory:
        path = Path(directory) / 'recording.audio'
        path.write_bytes(audio)
        try:
            with _lock:
                segments, _ = get_model().transcribe(str(path), language='ru', vad_filter=True,
                    beam_size=5, temperature=0, condition_on_previous_text=True,
                    initial_prompt='Планирование задач на русском языке. Занятия, пара в университете, волейбол, баскетбол, тренировка, встреча. Дни: завтра, суббота, воскресенье.')
                text = ' '.join(segment.text.strip() for segment in segments).strip()
        except (ValueError, av.error.FFmpegError) as error:
            raise HTTPException(422, 'Не удалось прочитать аудио. Попробуйте записать ещё раз.') from error
        except Exception as error:
            logging.getLogger(__name__).exception('Local transcription failed')
            raise HTTPException(503, 'Локальное распознавание недоступно. Проверьте логи backend.') from error
    if not text:
        raise HTTPException(422, 'Речь не обнаружена. Говорите ближе к микрофону и повторите запись.')
    return {'text': text, 'engine':'Whisper Small', 'warning':'Запасной движок: GigaAM недоступна.'}


def transcribe_audio(audio: bytes):
    started = perf_counter()
    speech_url = os.getenv('SPEECH_URL', 'http://speech:8001').rstrip('/')
    use_fallback = os.getenv('SPEECH_LOCAL_FALLBACK', '1') == '1'
    if not speech_url:
        if not use_fallback:
            raise HTTPException(503, 'Распознавание речи отключено на сервере. Введите команду текстом.')
        result = whisper_transcribe(audio)
        result['seconds'] = round(perf_counter() - started, 2)
        return result
    try:
        response=httpx.post(speech_url+'/transcribe',
            content=audio,headers={'Content-Type':'application/octet-stream'},timeout=120)
        if response.status_code in (413,415,422):
            raise HTTPException(response.status_code,response.json().get('detail','Проверьте запись.'))
        response.raise_for_status()
        result=response.json()
        if not isinstance(result.get('text'),str) or not result['text'].strip():
            raise ValueError('Empty GigaAM response')
        return result
    except (httpx.HTTPError, ValueError):
        if not use_fallback:
            raise HTTPException(503, 'Сервис распознавания речи недоступен. Попробуйте позже или введите команду текстом.') from None
        logging.getLogger(__name__).warning('GigaAM unavailable, using local Whisper',exc_info=True)
        result=whisper_transcribe(audio)
        result['seconds']=round(perf_counter()-started,2)
        return result
