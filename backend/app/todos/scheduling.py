"""Ground task dates and clocks in the task's own spoken fragment."""
from datetime import datetime, timedelta
import re
from zoneinfo import ZoneInfo
from fastapi import HTTPException
from app.plans.dates import ANCHOR, MONTHS, explicit_weekday_date, resolve_anchor, spoken_slots
from app.plans.colloquial_time import POINT, possible_minutes, resolve_colloquial_ranges
from app.plans.prompts import normalize_transcript

CARDINALS = {'один':'одного','два':'двух','три':'трёх','четыре':'четырёх',
             'пять':'пяти','шесть':'шести','семь':'семи','восемь':'восьми',
             'девять':'девяти','десять':'десяти','одиннадцать':'одиннадцати','двенадцать':'двенадцати'}


def grounded_schedule(action, source, zone_name):
    zone = ZoneInfo(zone_name)
    today = datetime.now(zone).date()
    day, at = action.scheduled_date, action.scheduled_at
    # A model's naive wall clock belongs to the explicit request timezone.
    # Public API inputs still require an offset.
    if at is not None and at.tzinfo is None:
        at = at.replace(tzinfo=zone)
    if action.clear_schedule:
        return {'scheduled_date': None, 'scheduled_at': None, 'timezone': zone_name}, False
    if not source:
        return {'scheduled_date': day, 'scheduled_at': at, 'timezone': zone_name}, bool(day or at)
    numeric = None
    anchors = list(ANCHOR.finditer(source))
    if anchors:
        dates = set()
        for match in anchors:
            value = resolve_anchor(match[0], today)
            explicit, _ = explicit_weekday_date(source[match.end():], today)
            if explicit:
                if explicit.weekday() != value.weekday():
                    raise HTTPException(422, 'Число и день недели не совпадают. Уточните дату задачи.')
                value = explicit
            if 'следующ' in source[max(0,match.start()-20):match.start()].lower() and value <= today:
                value += timedelta(days=7)
            dates.add(value)
        if len(dates) == 1:
            day = dates.pop()
        else:
            return {'scheduled_date': day, 'scheduled_at': at, 'timezone': zone_name}, True
    else:
        numeric = re.search(r'\b(\d{1,2})(?:[-–](?:го|ого|е|ое)(?:\s+числа)?|\s+числа|\s+(?:'+'|'.join(MONTHS)+r'))\b', source, re.I)
        if numeric:
            day, _ = explicit_weekday_date(source[numeric.start():], today)
    reviews = []
    spoken = normalize_transcript(resolve_colloquial_ranges(source, zone_name, reviews=reviews))
    slots = list(spoken_slots(spoken))
    clock = slots[0][1] if len(slots) == 1 else None
    if not clock:
        words = re.sub(r'\b('+'|'.join(CARDINALS)+r')\b', lambda m: CARDINALS[m[0].lower()], spoken, flags=re.I)
        point = re.search(rf'\b(?:в|во|на|к)\s+({POINT})\b', words, re.I)
        if point and re.search(r'\b(?:утра|дня|вечера|ночи)\b', point[1], re.I):
            minutes = possible_minutes(point[1])[0]
            clock = f'{minutes//60:02d}:{minutes%60:02d}'
    time_hint = bool(slots or re.search(r'\b(?:утра|дня|вечера|ночи)\b|\b(?:в|во|к)\s+(?:\d{1,2}|'+ '|'.join(CARDINALS) + r')\b',source,re.I))
    if not time_hint:
        at=None
    if action.clear_time:
        clock=None
        at=None
    if clock and day:
        hour, minute = map(int, clock.split(':'))
        at = datetime(day.year, day.month, day.day, hour, minute, tzinfo=zone)
    elif day and at is not None:
        local=at.astimezone(zone)
        at=local.replace(year=day.year,month=day.month,day=day.day)
    # Never silently attach an unspoken date supplied by the model.
    spoken_date = bool(anchors or numeric)
    if not spoken_date and (day or at):
        return {'scheduled_date': day, 'scheduled_at': at, 'timezone': zone_name}, True
    uncertain = bool(reviews or at and not clock)
    return {'scheduled_date': day, 'scheduled_at': at, 'timezone': zone_name}, uncertain


def task_fragment(text, title):
    from app.plans.dates import SENTENCE_BREAK, words
    fragments = [fragment.strip() for fragment in SENTENCE_BREAK.split(text) if fragment.strip()]
    target=set(words(title.replace('ё','е')))
    scores=[len(target & set(words(fragment.replace('ё','е')))) for fragment in fragments]
    best=max(scores,default=0)
    return fragments[scores.index(best)] if best and scores.count(best)==1 else ''
