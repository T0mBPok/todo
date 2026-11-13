from datetime import datetime,timedelta
import re
from zoneinfo import ZoneInfo
from fastapi import HTTPException
from app.plans.dates import ANCHOR,resolve_anchor
from app.plans.prompts import date_context
from app.tasks.schemas import TaskRead
from app.recurrences.service import instances, next_occurrence
from app.commands.matching import CHANGES_EXISTING, score_name, tokens

BROAD = re.compile(r'\b(?:кроме|остальн\w*|вс[её]\s+(?:задачи|события|мероприятия))\b', re.I)
REFERENCE = re.compile(r'\b(?:это|этот|эту|этого|е[её]|его)\b', re.I)
MOVE = re.compile(r'\b(?:перенес|перенёс|перенос|сдвин|передвин|перестав)\w*\b', re.I)


def targeted_rows(request, rows):
    if not CHANGES_EXISTING.search(request.text) or BROAD.search(request.text):
        return None
    terms = [word for word in tokens(request.text)
             if word.isalpha() and not CHANGES_EXISTING.fullmatch(word) and not ANCHOR.fullmatch(word)]
    named = [row for row in rows if any(score_name(term, row.title) for term in terms)]
    if named:
        return named
    if request.context_task_id and REFERENCE.search(request.text):
        return [row for row in rows if row.id == request.context_task_id]
    return None


def targeted_occurrences(task, request, explicit_windows, now, excluded):
    if task.id == request.context_task_id and request.context_occurrence_start:
        chosen = request.context_occurrence_start
        if not explicit_windows or MOVE.search(request.text) or any(start <= chosen < end for start, end in explicit_windows):
            selected = next((pair for pair in instances(task, chosen, chosen + timedelta(microseconds=1), excluded)
                             if pair[0] == chosen), None)
            if selected:
                return [selected]
    if explicit_windows:
        matches = {pair for start, end in explicit_windows for pair in instances(task, start, end, excluded)
                   if start <= pair[0] < end}
        if matches or not MOVE.search(request.text):
            return matches
    occurrence = next_occurrence(task, now, excluded) or next_occurrence(task, task.start, excluded)
    return [occurrence] if occurrence else []

def calendar_context(request,service):
    zone=ZoneInfo(request.timezone);now=datetime.now(zone)
    windows=[(now-timedelta(days=7),now+timedelta(days=15))]
    if request.calendar_start and request.calendar_end:
        if request.calendar_end<=request.calendar_start or request.calendar_end-request.calendar_start>timedelta(days=62):
            raise HTTPException(422,'Выберите диапазон календаря не более двух месяцев.')
        windows.append((request.calendar_start,request.calendar_end))
    explicit_windows=[]
    for match in ANCHOR.finditer(request.text):
        day=resolve_anchor(match.group(),now.date())
        if day:
            start=datetime.combine(day,datetime.min.time(),zone);explicit_windows.append((start,start+timedelta(days=1)))
    if explicit_windows:windows=explicit_windows
    rows = service.dao.list()
    targets = targeted_rows(request, rows)
    exceptions=service.recurrences.exceptions();values={};series=[];catalogue=[]
    for task in rows if targets is None else targets:
        catalogue.append({'id':str(task.id),'title':task.title,'start':task.start.astimezone(zone).isoformat(),'recurrence':task.recurrence})
        if task.recurrence:
            series.append({'id':str(task.id),'title':task.title,'description':task.description,'anchor':task.start.astimezone(zone).isoformat(),'recurrence':task.recurrence})
            excluded = exceptions.get(task.id, set())
            if targets is None:
                pairs = {pair for start, end in windows for pair in instances(task, start, end, excluded)}
            else:
                pairs = targeted_occurrences(task, request, explicit_windows, now, excluded)
        else:
            relevant=not explicit_windows or any(task.start<end and task.end>start for start,end in windows)
            pairs={(task.start,task.end)} if relevant else set()
        for start,end in sorted(pairs):
            value=TaskRead.model_validate(task);value.start=start;value.end=end
            if task.recurrence:value.occurrence_start=start
            values[(str(task.id),start.isoformat())]=value
    ordered=sorted(values.values(),key=lambda t:(t.start,str(t.id)))
    if len(ordered)>180:raise HTTPException(422,'В контексте слишком много событий. Назовите точную дату и выберите вид «День» или «Неделя».')
    mapping={f'E{i+1}':task for i,task in enumerate(ordered)}
    events=[{'ref':key,'id':str(task.id),'title':task.title,'description':task.description,
        'start':task.start.astimezone(zone).isoformat(),'end':task.end.astimezone(zone).isoformat(),
        'weekday':task.start.astimezone(zone).strftime('%A'),'recurrence':task.recurrence.model_dump() if task.recurrence else None,
        'selected':task.id==request.context_task_id and (request.context_occurrence_start is None or task.start==request.context_occurrence_start)} for key,task in mapping.items()]
    context={'now':now.isoformat(),'timezone':request.timezone,'date_context':date_context(request.timezone),'visible_range':{'start':str(request.calendar_start),'end':str(request.calendar_end)},'events':events,'series':series,'catalogue':catalogue}
    return context,mapping
