"""Recognize requests to repeat existing calendar events without recreating them."""
import re
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from app.plans.dates import WEEKDAYS,words
from fastapi import HTTPException
from app.commands.schemas import Interpretation,Operation

def conversion_requested(text):
    return bool(re.search(r'(?:сдела\w*|сделать|сделай|сделаем|стали|станут|были|пусть|нужно|надо).*повторя|повторя.*(?:существующ|уже|которые)|повторять.*(?:существующ|уже)',text,re.I|re.S))

def existing_recurrence(request,tasks,now=None):
    if not conversion_requested(request.text) or re.search(r"(?:добав|созда|сдела)\w*\s+нов",request.text,re.I): return None
    zone=ZoneInfo(request.timezone);current=(now or datetime.now(zone)).astimezone(zone)
    days={value for stem,value in WEEKDAYS.items() if re.search(r'\b'+stem+r'[а-яё]*',request.text,re.I)}
    if not days: return None
    tokens=set(words(request.text));groups={}
    for task in tasks:
        local=task.start.astimezone(zone)
        if local.weekday() not in days or task.series_parent_id: continue
        if not task.recurrence and (task.start<current or task.start>current+timedelta(days=21)): continue
        # Match a spoken event name, never every event just because its day matches.
        if not (set(words(task.title)) & tokens): continue
        key=(task.title.casefold(),local.weekday(),local.hour,local.minute)
        previous=groups.get(key)
        if previous is None or task.start<previous.start: groups[key]=task
    if not groups: return None
    missing=days-{key[1] for key in groups}
    if missing:
        names=['понедельник','вторник','среда','четверг','пятница','суббота','воскресенье']
        raise HTTPException(422,'Не нашёл существующие задачи на дни: '+', '.join(names[d] for d in sorted(missing))+'. Уточните название или скажите «добавь новые тренировки» с указанием времени.')
    operations=[]
    for task in sorted(groups.values(),key=lambda t:t.start):
        local=task.start.astimezone(zone)
        date=local.date()
        if task.recurrence:
            date=current.date()+timedelta(days=(local.weekday()-current.weekday())%7)
            if datetime.combine(date,local.timetz())<current: date+=timedelta(days=7)
        operations.append(Operation(operation='update',target=task.title,date_reference=date.isoformat(),time_reference=local.strftime('%H:%M'),scope='series',new_recurrence='weekly'))
    return Interpretation(intent='manage',operations=operations)
