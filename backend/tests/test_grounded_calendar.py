from test_api import client
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from app.commands.grounded_ai import Decision,SelectedOperation
from app.commands.context import calendar_context
from app.commands.schemas import CommandRequest
from app.tasks.service import TaskService

def seed(api):
    zone=ZoneInfo('Asia/Tomsk');now=datetime.now(zone)
    saturday=(now+timedelta(days=(5-now.weekday())%7)).date()
    values=[]
    for title,day,hour in [('Пара в университете',saturday,13),('Волейбол',saturday,11),('Баскетбол',saturday,12),('Тренировка по волейболу',saturday+timedelta(days=1),11)]:
        start=datetime.combine(day,datetime.min.time(),zone)+timedelta(hours=hour)
        response=api.post('/api/tasks',json={'title':title,'description':'Реальные детали','start':start.isoformat(),'end':(start+timedelta(hours=1)).isoformat()})
        assert response.status_code==201,response.text
        values.append(response.json())
    return values

def test_model_gets_dates_descriptions_ids_history_and_returns_bound_actions(client,monkeypatch):
    api,_=client;tasks=seed(api)
    def interpret(request,context):
        assert request.history[0].text=='Предыдущая команда'
        assert len(context['events'])==3
        assert len(context['catalogue'])==4
        assert all(e['id'] and e['start'] and e['end'] and e['description']=='Реальные детали' for e in context['events'])
        keep=[e['ref'] for e in context['events'] if e['title']=='Пара в университете']
        selected=[e['ref'] for e in context['events'] if e['title'] in ['Волейбол','Баскетбол']]
        return Decision(intent='manage',note='Сохранить пару, убрать остальные события субботы.',keep_refs=keep,operations=[SelectedOperation(action='delete',refs=selected,selection='all',scope='occurrence')])
    monkeypatch.setattr('app.commands.grounded_ai.interpret_calendar',interpret)
    response=api.post('/api/commands',json={'text':'Мне надо чтобы ты в субботу убрал всё кроме пары в универе','history':[{'role':'user','text':'Предыдущая команда'}]})
    assert response.status_code==200,response.text
    command=response.json();assert len(command['operations'])==2
    assert all(op['requires_confirmation'] for op in command['operations'])
    result=api.post('/api/commands/'+command['id']+'/execute',json={'choices':[{'candidate':0},{'candidate':0}]})
    assert result.status_code==200,result.text
    remaining=api.get('/api/tasks').json()
    assert {t['id'] for t in remaining}=={tasks[0]['id'],tasks[3]['id']}

def test_unknown_reference_rejected(client,monkeypatch):
    api,_=client;seed(api)
    monkeypatch.setattr('app.commands.grounded_ai.interpret_calendar',lambda *a:Decision(intent='manage',note='Удалить',operations=[SelectedOperation(action='delete',refs=['FAKE'])]))
    response=api.post('/api/commands',json={'text':'Удали пару в субботу'})
    assert response.status_code==502
    assert len(api.get('/api/tasks').json())==4

def test_wrong_day_rejected_even_for_existing_id(client,monkeypatch):
    api,_=client;seed(api)
    def wrong(request,context):
        ref=context['events'][0]['ref']
        context['events'][0]['title']='Wrong day'
        return Decision(intent='manage',note='Удалить',operations=[SelectedOperation(action='delete',refs=[ref])])
    from app.commands.context import calendar_context as real_context
    def altered_context(request,service):
        context,mapping=real_context(request,service)
        value=next(iter(mapping.values()))
        value.start+=timedelta(days=1);value.end+=timedelta(days=1)
        return context,mapping
    monkeypatch.setattr('app.commands.context.calendar_context',altered_context)
    monkeypatch.setattr('app.commands.grounded_ai.interpret_calendar',wrong)
    response=api.post('/api/commands',json={'text':'Удали пару в субботу'})
    assert response.status_code==422 and 'другом дне' in response.json()['detail']

def test_ambiguous_refs_become_choices_not_batch(client,monkeypatch):
    api,_=client;seed(api)
    def ambiguous(request,context):
        return Decision(intent='manage',note='Какой волейбол?',operations=[SelectedOperation(action='delete',refs=[e['ref'] for e in context['events'] if 'олейбол' in e['title']])])
    monkeypatch.setattr('app.commands.grounded_ai.interpret_calendar',ambiguous)
    response=api.post('/api/commands',json={'text':'Удали волейбол'})
    assert response.status_code==200,response.text
    assert len(response.json()['operations'])==1
    assert len(response.json()['operations'][0]['candidates'])==2

def test_protected_reference_never_executed(client,monkeypatch):
    api,_=client;seed(api)
    def invalid(request,context):
        ref=context['events'][0]['ref']
        return Decision(intent='manage',note='Ошибка',keep_refs=[ref],operations=[SelectedOperation(action='delete',refs=[ref])])
    monkeypatch.setattr('app.commands.grounded_ai.interpret_calendar',invalid)
    assert api.post('/api/commands',json={'text':'Удали всё кроме пары в субботу'}).status_code==502

def test_clear_question_and_no_mutation(client,monkeypatch):
    api,_=client;seed(api)
    monkeypatch.setattr('app.commands.grounded_ai.interpret_calendar',lambda *a:Decision(intent='clarify',note='На какую дату перенести пару?'))
    response=api.post('/api/commands',json={'text':'Перенеси пару'})
    assert response.status_code==422 and response.json()['detail']=='На какую дату перенести пару?'
    assert len(api.get('/api/tasks').json())==4
