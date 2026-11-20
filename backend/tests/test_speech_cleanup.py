from app.voice.service import polish_transcript
from app.plans.ai import AIPlanner

def test_cleanup_keeps_the_raw_recording_and_uses_the_language_model(monkeypatch):
    calls=[]
    def normalize(self,text):
        calls.append(text)
        return 'Завтра тренировка с 18:00 до 19:00.',''
    monkeypatch.setattr(AIPlanner,'normalize',normalize)
    original='завтра тренеровка с 18:00 до 19:00'
    result=polish_transcript({'text':original,'engine':'GigaAM v3'})
    assert calls==[original]
    assert result['raw_text']==original
    assert result['text']=='Завтра тренировка с 18:00 до 19:00.'
    assert result['postprocessed'] is True

def test_cleanup_failure_preserves_original_text(monkeypatch):
    def offline(self,text):raise RuntimeError('private-token')
    monkeypatch.setattr(AIPlanner,'normalize',offline)
    result=polish_transcript({'text':'Созвон завтра в восемь','engine':'GigaAM v3'})
    assert result['text']==result['raw_text']=='Созвон завтра в восемь'
    assert result['postprocessed'] is False
    assert 'private' not in result['warning']
    assert 'исходный текст' in result['warning']

def test_cleanup_cannot_silently_shift_explicit_time(monkeypatch):
    import httpx,json
    from app.core import config
    monkeypatch.setattr(config,'AI_PROVIDER','ollama')
    monkeypatch.setattr(httpx,'post',lambda url,**kwargs:httpx.Response(200,request=httpx.Request('POST',url),
        json={'message':{'content':json.dumps({'text':'Завтра тренировка с 01:00 до 02:00.','note':''})}}))
    result=polish_transcript({'text':'Завтра тренировка с 18:00 до 19:00.'})
    assert result['text']=='Завтра тренировка с 18:00 до 19:00.'

def test_cleanup_cannot_change_spoken_numbers_or_time_of_day(monkeypatch):
    monkeypatch.setattr(AIPlanner,'normalize',lambda self,text:('Тренировка завтра с восьми до девяти утра.',''))
    raw='Тренировка завтра с восемнадцати до девятнадцати вечера.'
    assert polish_transcript({'text':raw})['text']==raw
