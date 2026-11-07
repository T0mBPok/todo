"""Resolve explicit date anchors in speech independently of model arithmetic."""
import re
from datetime import date, datetime, timedelta
from fastapi import HTTPException
from zoneinfo import ZoneInfo

WEEKDAYS = {'понедельник':0, 'вторник':1, 'сред':2, 'четверг':3, 'пятниц':4, 'суббот':5, 'воскресень':6}
ANCHOR = re.compile(r'\b(?:послезавтра|завтра|сегодня|понедельник[а-я]*|вторник[а-я]*|сред[ауые]|четверг[а-я]*|пятниц[а-я]*|суббот[а-я]*|воскресень[а-я]*|\d{4}-\d{2}-\d{2})\b', re.I)
MONTHS = ('января','февраля','марта','апреля','мая','июня','июля','августа','сентября','октября','ноября','декабря')
DAY_AFTER = re.compile(r'^[\s,]*(?:числа\s+)?(\d{1,2})(?:\s*[-–]?\s*(?:го|ого|е|ое))?(?![\d:])(?:\s+(' + '|'.join(MONTHS) + r'))?(?:\s+(\d{4})(?:\s*года)?)?\b', re.I)

def explicit_weekday_date(tail, today):
    match = DAY_AFTER.match(tail)
    if not match:
        return None, 0
    day = int(match[1])
    month = MONTHS.index(match[2].lower()) + 1 if match[2] else today.month
    year = int(match[3]) if match[3] else today.year
    try:
        target = date(year, month, day)
    except ValueError as error:
        raise HTTPException(422, 'Такой даты нет. Уточните число и месяц.') from error
    if target < today and not match[3]:
        if match[2]:
            year += 1
        else:
            year, month = (year + 1, 1) if month == 12 else (year, month + 1)
        try:
            target = date(year, month, day)
        except ValueError as error:
            raise HTTPException(422, 'Уточните месяц для указанного числа.') from error
    return target, match.end()

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
        explicit, consumed = explicit_weekday_date(text[match.end():], today) if any(match.group().lower().startswith(stem) for stem in WEEKDAYS) else (None, 0)
        if explicit is not None:
            if explicit.weekday() != day.weekday():
                raise HTTPException(422, 'Указанные число и день недели не совпадают. Уточните дату.')
            day = explicit
        before=text[max(0,match.start()-20):match.start()].lower()
        if explicit is None and 'следующ' in before and day == today:
            day += timedelta(days=7)
        end=anchors[i+1].start() if i+1<len(anchors) else len(text)
        segments.append((day,words(text[match.end()+consumed:end])))
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
