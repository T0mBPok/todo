from contextlib import asynccontextmanager
from tempfile import TemporaryDirectory
from pathlib import Path
from threading import Lock
from time import perf_counter
import subprocess
import logging
import numpy as np
import soundfile as sf
import torch
import gigaam
from fastapi import FastAPI, HTTPException, Request
from starlette.concurrency import run_in_threadpool
from audio import split_audio, SAMPLE_RATE

torch.set_num_threads(4)
model=None
lock=Lock()

def load():
    global model
    model=gigaam.load_model('v3_e2e_ctc', download_root='/models/gigaam', device='cpu', use_flash=False)

@asynccontextmanager
async def lifespan(app):
    await run_in_threadpool(load)
    yield

app=FastAPI(lifespan=lifespan)

@app.get('/health')
def health():
    return {'ready':model is not None,'engine':'GigaAM v3'}

def recognize(data):
    started=perf_counter()
    with TemporaryDirectory() as directory:
        source=Path(directory)/'audio'
        source.write_bytes(data)
        try:
            decoded=subprocess.run(['ffmpeg','-v','error','-nostdin','-i',str(source),
                '-t','91','-f','f32le','-ac','1','-ar',str(SAMPLE_RATE),'-'],
                capture_output=True,timeout=20)
        except subprocess.TimeoutExpired as error:
            raise HTTPException(422,'Не удалось декодировать запись.') from error
        if decoded.returncode:
            raise HTTPException(422,'Не удалось прочитать аудио. Повторите запись.')
        audio=np.frombuffer(decoded.stdout,dtype=np.float32)
        if len(audio)>90.5*SAMPLE_RATE:
            raise HTTPException(422,'Максимальная длительность записи — 90 секунд.')
        if not len(audio) or np.max(np.abs(audio))<0.001:
            raise HTTPException(422,'Запись слишком тихая или пустая. Проверьте микрофон.')
        texts=[]
        try:
            with lock, torch.inference_mode():
                for index,chunk in enumerate(split_audio(audio)):
                    if np.max(np.abs(chunk))<0.001:
                        continue
                    path=Path(directory)/f'chunk-{index}.wav'
                    sf.write(path,chunk,SAMPLE_RATE,subtype='PCM_16')
                    result=model.transcribe(str(path))
                    text=result.text if hasattr(result,'text') else str(result)
                    if text.strip():
                        texts.append(text.strip())
        except Exception as error:
            logging.getLogger(__name__).exception('GigaAM transcription failed')
            raise HTTPException(503,'GigaAM не смогла обработать запись.') from error
    text=' '.join(texts).strip()
    if not text:
        raise HTTPException(422,'Речь не обнаружена. Повторите запись.')
    return {'text':text,'engine':'GigaAM v3','seconds':round(perf_counter()-started,2),'warning':''}

@app.post('/transcribe')
async def transcribe(request:Request):
    data=bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data)>12*1024*1024:
            raise HTTPException(413,'Слишком большая запись.')
    if not data:
        raise HTTPException(422,'Пустая запись.')
    return await run_in_threadpool(recognize,bytes(data))
