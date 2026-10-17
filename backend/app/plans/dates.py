"""Resolve explicit date anchors in speech independently of model arithmetic."""
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

WEEKDAYS = {'понедельник':0, 'вторник':1, 'сред':2, 'четверг':3, 'пятниц':4, 'суббот':5, 'воскресень':6}
ANCHOR = re.compile(r'\b(?:послезавтра|завтра|сегодня|понедельник[а-я]*|вторник[а-я]*|сред[ауые]|четверг[а-я]*|пятниц[а-я]*|суббот[а-я]*|воскресень[а-я]*|\d{4}-\d{2}-\d{2})\b', re.I)
STOP = {'потом','после','сразу','будет','меня','университете','завтра','сегодня','него'}

def resolve_anchor(word, today):
    word = word.lower()
    if word in ('сегодня','завтра','послезавтра'):
        return today + timedelta(days={'сегодня':0,'завтра':1,'послезавтра':2}[word])
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', word):
        return datetime.strptime(word, '%Y-%m-%d').date()
    for stem, weekday in WEEKDAYS.items():
        if word.startswith(stem):
            return today + timedelta(days=(weekday-today.weekday()) % 7)
    return None

def words(text):
    return [word[:5] for word in re.findall(r'[а-яё]+', text.lower()) if len(word)>2 and word not in STOP]

def enforce_date_context(tasks, text, timezone, now=None):
    zone=ZoneInfo(timezone)
    today=(now or datetime.now(zone)).astimezone(zone).date()
    anchors=list(ANCHOR.finditer(text))
    if not anchors:
        return tasks
    segments=[]
    for i, match in enumerate(anchors):
        day=resolve_anchor(match.group(),today)
        before=text[max(0,match.start()-20):match.start()].lower()
        if 'следующ' in before and day == today:
            day += timedelta(days=7)
        end=anchors[i+1].start() if i+1<len(anchors) else len(text)
        segments.append((day,words(text[match.end():end])))
    for task in tasks:
        title=words(task.title)
        scores=[sum(1 for word in title if word in segment) for _,segment in segments]
        best=max(scores, default=0)
        # Unambiguous title match, or one date applying to the whole request.
        candidates=[i for i,score in enumerate(scores) if score==best]
        if len(segments)==1:
            index=0
        elif best and len(candidates)==1:
            index=candidates[0]
        else:
            continue
        target=segments[index][0]
        local_start=task.start.astimezone(zone)
        duration=task.end-task.start
        task.start=local_start.replace(year=target.year,month=target.month,day=target.day)
        task.end=task.start+duration
    return tasks
