from datetime import datetime, timezone
from app.plans.prompts import date_context, planning_prompt, normalize_transcript

def test_relative_dates_use_user_timezone_across_year_boundary():
    now = datetime(2026, 12, 31, 18, 0, tzinfo=timezone.utc)
    context = date_context('Asia/Tomsk', now)
    assert context['относительные_даты'] == {
        'сегодня': '2027-01-01', 'завтра': '2027-01-02', 'послезавтра': '2027-01-03'}
    assert context['ближайшие_дни'][0]['день_недели'] == 'пятница'

def test_context_resolves_tomorrow_without_weekday_question():
    now = datetime.fromisoformat('2026-10-16T21:00:00+07:00')
    prompt = planning_prompt('Asia/Tomsk', [], {}, now)
    assert '"завтра": "2026-10-17"' in prompt
    assert 'пару' in prompt.lower()
    assert '13:15' in prompt
    assert 'needs_clarification=false' in prompt

def test_spoken_durations_are_normalized_without_changing_other_text():
    assert normalize_transcript('Завтра пара на полтора часа, потом полчаса почта.') == 'Завтра пара на 90 минут, потом 30 минут почта.'
    assert normalize_transcript('Встреча в 10:15 на 45 минут.') == 'Встреча в 10:15 на 45 минут.'

def test_time_separator_normalization_preserves_dates():
    assert normalize_transcript('В 13-15 и 13-12, дата 2026-10-18') == 'В 13:15 и 13:12, дата 2026-10-18'

def test_normalizer_cannot_change_explicit_time(monkeypatch):
    import json
    import httpx
    from app.plans.ai import AIPlanner
    def fake_post(url, **kwargs):
        return httpx.Response(200, request=httpx.Request('POST',url), json={
            'message':{'content':json.dumps({'text':'Баскетбол в 13:00','note':'исправлено'})}})
    monkeypatch.setattr(httpx, 'post', fake_post)
    assert AIPlanner().normalize('Баскетбол в 13-12') == ('Баскетбол в 13:12', '')

def test_normalizer_passes_correction_to_planning(monkeypatch):
    import json
    import httpx
    from app.plans.ai import AIPlanner
    from app.plans.schemas import PlanRequest
    calls=[]
    def fake_post(url, **kwargs):
        calls.append(kwargs['json'])
        if len(calls)==1:
            content={'text':'В воскресенье волейбол в 11:00','note':'Исправлено название спорта'}
        else:
            assert calls[-1]['messages'][1]['content'].startswith('В воскресенье волейбол в 11:00')
            assert 'Исходный текст' in calls[-1]['messages'][1]['content']
            content={'tasks':[{'title':'Волейбол','start':'2026-10-18T11:00:00+07:00','end':'2026-10-18T12:00:00+07:00'}], 'note':'Понял', 'needs_clarification':False}
        return httpx.Response(200,request=httpx.Request('POST',url),json={'message':{'content':json.dumps(content)}})
    monkeypatch.setattr(httpx,'post',fake_post)
    import app.plans.ai as ai_module
    from app.plans.dates import enforce_date_context
    monkeypatch.setattr(ai_module, 'enforce_date_context', lambda tasks,text,zone: enforce_date_context(tasks,text,zone,datetime.fromisoformat('2026-10-16T21:00:00+07:00')))
    result=AIPlanner().generate(PlanRequest(text='В воскресенье в либол в 11:00'),[])
    assert result.tasks[0].title=='Волейбол'
    assert 'Волейбол: 18.10 11:00–12:00' in result.note

def test_asr_short_minute_is_padded():
    assert normalize_transcript('Волейбол в 11:0, баскетбол в 13:12.') == 'Волейбол в 11:00, баскетбол в 13:12.'


def test_normalizer_cannot_drop_explicit_day(monkeypatch):
    import json
    import httpx
    from app.plans.ai import AIPlanner
    def fake_post(url, **kwargs):
        return httpx.Response(200,request=httpx.Request('POST',url),json={'message':{'content':json.dumps({'text':'В среду Сейсмон в 11:00','note':''})}})
    monkeypatch.setattr(httpx,'post',fake_post)
    assert AIPlanner().normalize('В среду 28-го Сейсмон в 11:00')[0]=='В среду 28-го Сейсмон в 11:00'
