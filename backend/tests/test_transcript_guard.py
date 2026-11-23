import itertools
import json
from datetime import datetime
from zoneinfo import ZoneInfo
import httpx
import pytest
from app.plans.transcript_guard import safe_transcript_edit
from app.plans import ai
from app.commands import grounded_ai
from test_api import client

# Generated unseen letter fragments exercise a structural rule, not a typo list.
@pytest.mark.parametrize('letters',[''.join(x) for x in itertools.product('ндяч',repeat=3)])
@pytest.mark.parametrize('zeros',['0','00','000'])
def test_unknown_clock_word_residue_can_be_repaired(letters,zeros):
    before=f'На пятницу 27-го пары с 12:00 {zeros}{letters} до 13:00 дня.'
    after='На пятницу 27-го пары с 12:00 дня до 13:00 дня.'
    assert safe_transcript_edit(before,after)

@pytest.mark.parametrize(('before','after'),[
 ('Завтра созвон в 08:00.','Завтра созвон в 15:00.'),
 ('Завтра созвон в 08:00 утра.','Завтра созвон в 08:00 вечера.'),
 ('Завтра созвон в 08:00 вечера.','Завтра созвон в 08:00.'),
 ('Завтра созвон в 08:00 0н.','Завтра созвон в 08:00 вечера.'),
 ('В пятницу 27-го пары в 12:00.','В пятницу 28-го пары в 12:00.'),
 ('Завтра созвон в 12:77.','Завтра созвон в 12:00.'),
 ('Завтра созвон в 12.05.','Завтра созвон в 12:05.'),
 ('Завтра созвон в 12:0:30.','Завтра созвон в 12:00.'),
 ('Завтра в 12:00 на 30 минут созвон.','Завтра в 12:00 на 60 минут созвон.'),
 ('Завтра в 12:00 0минут созвон.','Завтра в 12:00 созвон.'),
 ('Завтра работа в 08:00. Пары в 12:00.','Завтра работа в 12:00. Пары в 08:00.'),
])
def test_edit_cannot_change_temporal_meaning(before,after):
    assert not safe_transcript_edit(before,after)


def test_screenshot_ai_repair_reaches_display_and_calendar_without_utc_shift(client,monkeypatch):
    api,_=client
    source='На пятницу 27-го поставь работу с 08:00 до 09:00. Пары с 12:00 0н до 13:00 дня и встречу с друзьями с 18:00 до 19:00.'
    clean=source.replace('12:00 0н','12:00 дня')
    monkeypatch.setattr(ai.config,'AI_PROVIDER','gigachat')
    plan=ai.ExtractedPlan(tasks=[
      {'title':title,'start':f'2026-11-27T{start}:00:00Z','end':f'2026-11-27T{end}:00:00Z'}
      for title,start,end in [('Работа','08','09'),('Пары','12','13'),('Встреча с друзьями','18','19')]],note='',needs_clarification=False)
    def model(url,**kw):
        content=json.dumps({'text':clean,'note':'Исправлено повреждённое слово рядом со временем.'}) if kw['operation']=='transcript_normalization' else plan.model_dump_json()
        return httpx.Response(200,request=httpx.Request('POST',url),json={'message':{'content':content}})
    monkeypatch.setattr(ai,'ai_post',model)
    result=api.post('/api/commands',json={'text':source,'timezone':'Asia/Tomsk'})
    assert result.status_code==200,result.text
    draft=result.json()['plan']
    assert draft['normalized_text']==clean
    assert draft['review']==[]
    saved=api.post('/api/plans/'+draft['id']+'/confirm',json={'tasks':draft['tasks']})
    assert saved.status_code==200,saved.text
    tasks=api.get('/api/tasks').json()
    actual={t['title']:tuple(datetime.fromisoformat(t[k]).astimezone(ZoneInfo('Asia/Tomsk')).strftime('%H:%M') for k in ('start','end')) for t in tasks}
    assert actual=={'Работа':('08:00','09:00'),'Пары':('12:00','13:00'),'Встреча с друзьями':('18:00','19:00')}

@pytest.mark.parametrize('fragment',['0н','в0ра','в00ра','д0ня','дн0я','дня0','0дня','неиз0вестно'])
def test_zero_inside_any_part_of_adjacent_word_does_not_change_numeric_clocks(fragment):
    assert safe_transcript_edit(f'Встреча с 18:00 до 19:00 {fragment}.','Встреча с 18:00 до 19:00 вечера.')


def test_rejected_whole_transcript_edit_still_grounds_clear_numeric_ranges(client,monkeypatch):
    api,_=client
    source='На пятницу 27-го поставь работу с 08:00 до 09:00. пары с 12:00 0н до 13:00 дня и встречу с друзьями с 18:00 до 19:00 в0ра.'
    monkeypatch.setattr(ai.config,'AI_PROVIDER','gigachat')
    # Even an unavailable/rejected cleanup cannot leave UTC model values in place.
    monkeypatch.setattr(ai.AIPlanner,'normalize',lambda self,text:(text,''))
    plan=ai.ExtractedPlan(tasks=[
      {'title':title,'start':f'2026-11-27T{start}:00:00Z','end':f'2026-11-27T{end}:00:00Z'}
      for title,start,end in [('Работа','08','09'),('Пары','12','13'),('Встреча с друзьями','18','19')]],note='',needs_clarification=False)
    monkeypatch.setattr(ai,'ai_post',lambda url,**kw:httpx.Response(200,request=httpx.Request('POST',url),json={'message':{'content':plan.model_dump_json()}}))
    response=api.post('/api/commands',json={'text':source,'timezone':'Asia/Tomsk'})
    assert response.status_code==200,response.text
    draft=response.json()['plan']
    assert draft['review']==[],draft
    assert [(datetime.fromisoformat(t['start']).astimezone(ZoneInfo('Asia/Tomsk')).strftime('%H:%M'),datetime.fromisoformat(t['end']).astimezone(ZoneInfo('Asia/Tomsk')).strftime('%H:%M')) for t in draft['tasks']]==[('08:00','09:00'),('12:00','13:00'),('18:00','19:00')]
    saved=api.post('/api/plans/'+draft['id']+'/confirm',json={'tasks':draft['tasks']})
    assert saved.status_code==200,saved.text


def test_unknown_daypart_of_small_hour_is_not_silently_dropped():
    from app.plans.transcript_guard import explicit_clock_text
    text='Встреча с 06:00 в0ра до 07:00 в0ра.'
    assert explicit_clock_text(text)==text


def test_clear_clock_debris_is_not_sent_to_llm_as_an_invitation_to_invent_a_location(monkeypatch):
    raw='Встреча с друзьями с 18:00 до 19:00 в0ра.'
    def model(url,**kw):
        assert kw['json']['messages'][1]['content']=='Встреча с друзьями с 18:00 до 19:00.'
        return httpx.Response(200,request=httpx.Request('POST',url),json={'message':{'content':json.dumps({'text':'Встреча с друзьями с 18:00 до 19:00.','note':''})}})
    monkeypatch.setattr(ai,'ai_post',model)
    assert ai.AIPlanner().normalize(raw)[0]=='Встреча с друзьями с 18:00 до 19:00.'
