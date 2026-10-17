import re
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from app.recurrences.schemas import RecurrenceRule
from app.plans.dates import words,WEEKDAYS

DAY=r'(?:понедельник[а-яё]*|вторник[а-яё]*|сред[а-яё]*|четверг[а-яё]*|пятниц[а-яё]*|суббот[а-яё]*|воскресень[а-яё]*)'
DAY_LIST=DAY+r'(?:\s*(?:,\s*(?:и\s+)?|и\s+|а\s+также\s+)(?:кажд[а-яё]*\s+|по\s+)?'+DAY+r')*'
PATTERN=re.compile(r'\b(?:(?:кажд[а-яё]*|по)\s+('+DAY_LIST+r')|(ежедневно|каждый\s+день)|(еженедельно))\b',re.I)

def apply_spoken_recurrence(tasks,text,timezone,now=None):
    matches=list(PATTERN.finditer(text))
    if not matches and re.search(r'повторяющ|еженедель',text,re.I):
        text=re.sub(r'\b(?:во?|по)\s+(?='+DAY+r')','каждый ',text,flags=re.I)
        matches=list(PATTERN.finditer(text))
    zone=ZoneInfo(timezone)
    current=(now or datetime.now(zone)).astimezone(zone)
    # A recurrence must come from an explicit request, not model invention.
    for task in tasks: task.recurrence=None
    if not matches:
        return tasks
    segments=[]
    for index,match in enumerate(matches):
        end=matches[index+1].start() if index+1<len(matches) else len(text)
        prefix=text[max(0,match.start()-80):match.start()]
        prefix=re.split(r'[.!?;]',prefix)[-1]
        segments.append(words(prefix+' '+text[match.end():end]))
    seen=set(); result=[]
    for task in tasks:
        scores=[sum(token in segment for token in words(task.title)) for segment in segments]
        best=max(scores,default=0)
        candidates=[i for i,score in enumerate(scores) if score==best]
        if len(tasks)==1 and len(matches)==1: selected=0
        elif best and len(candidates)==1: selected=candidates[0]
        else:
            result.append(task);continue
        match=matches[selected]
        frequency='daily' if match[2] else 'weekly'
        start=task.start.astimezone(zone)
        duration=task.end-task.start
        weekdays=[]
        if match[1]:
            weekdays=[next(value for stem,value in WEEKDAYS.items() if day.lower().startswith(stem)) for day in re.findall(DAY,match[1],re.I)]
        for weekday in dict.fromkeys(weekdays or [None]):
            occurrence=task.model_copy(deep=True) if len(weekdays)>1 else task
            start=task.start.astimezone(zone)
            if weekday is not None:
                distance=(weekday-current.weekday())%7 or 7
                target=current.date()+timedelta(days=distance)
                start=start.replace(year=target.year,month=target.month,day=target.day)
            elif frequency=='daily':
                start=start.replace(year=current.year,month=current.month,day=current.day)
                if start<=current: start+=timedelta(days=1)
            else:
                while start<=current: start+=timedelta(days=7)
            occurrence.start=start; occurrence.end=start+duration
            occurrence.recurrence=RecurrenceRule(frequency=frequency,timezone=timezone)
            key=(occurrence.title.lower(),start.weekday(),start.hour,start.minute,frequency)
            if key not in seen:
                seen.add(key);result.append(occurrence)
    return result
