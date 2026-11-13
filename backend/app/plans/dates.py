"""Resolve explicit date anchors in speech independently of model arithmetic."""
import re
from collections import Counter
from datetime import date, datetime, timedelta, timezone
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

CLOCK = r'(?<![\d:])(?:[01]?\d|2[0-3]):[0-5]\d(?![\d:])'
TIME_RANGE = re.compile(rf'\b(?:с\s+)?({CLOCK})(?:\s+до\s+|\s*[-–—]\s*)({CLOCK})', re.I)
START_TIME = re.compile(rf'\b(?:в|во|на|к)\s+({CLOCK})', re.I)
SHORT_CLOCK = re.compile(r'(?<![\d:])([01]?\d|2[0-3]):([0-5]?\d)(?![\d:])')
COMPACT_RANGE_END = re.compile(rf'({CLOCK}\s+до\s+)([01]\d|2[0-3])([0-5]\d)\b(?![.:]\d)', re.I)


def normalize_clock_minutes(text):
    text = SHORT_CLOCK.sub(lambda match: f'{int(match[1]):02d}:{int(match[2]):02d}', text)
    return COMPACT_RANGE_END.sub(r'\1\2:\3', text)


DETAIL_MARKER = re.compile(r'\b(?:в\s+описании|описание(?:\s+задачи)?|детали)\s*[:—-]', re.I)


DURATION = re.compile(r'\b(?:час\w*|минут\w*|секунд\w*|полчаса|полтора|полторы)\b', re.I)
EXPLICIT_DURATION = re.compile(
    r'\bна\s+(?:(\d{1,4}(?:[,.]\d{1,2})?)\s+)?(час(?:а|ов)?|минут(?:у|ы)?|секунд(?:у|ы)?)\b', re.I,
)


def spoken_duration(clause):
    match = EXPLICIT_DURATION.search(clause)
    if not match:
        return None
    value = float((match[1] or '1').replace(',', '.'))
    unit = match[2].casefold()
    seconds = 3600 if unit.startswith('час') else 60 if unit.startswith('минут') else 1
    return timedelta(seconds=value * seconds) if value else None
SENTENCE_BREAK = re.compile(r'\.(?!\d)|[!?;]')
CLAUSE_BREAK = re.compile(r',\s*|\s+(?:и|а|потом|затем)\s+', re.I)


def spoken_slots(text):
    for sentence in SENTENCE_BREAK.split(normalize_clock_minutes(text)):
        sentence = DETAIL_MARKER.split(sentence, maxsplit=1)[0]
        clock_count = len(re.findall(CLOCK, sentence))
        if clock_count > 1 and re.search(r'\b(?:ой[,\s]+нет|точнее|пардон)\b', sentence, re.I):
            continue
        single_slot_size = 2 if TIME_RANGE.search(sentence) else 1
        clauses = CLAUSE_BREAK.split(sentence) if clock_count > single_slot_size else [sentence]
        for clause in clauses:
            clocks = re.findall(CLOCK, clause)
            interval = TIME_RANGE.search(clause) if len(clocks) == 2 else None
            start = START_TIME.search(clause) if len(clocks) == 1 else None
            if interval or start:
                yield clause, (interval or start)[1], interval[2] if interval else None


def enforce_spoken_time(tasks, text, timezone_name, *alternatives):
    """Apply explicit wall-clock times by matching each event to its own clause."""
    zone = ZoneInfo(timezone_name)
    now = datetime.now(zone)
    resolved = set()
    fully_timed = None
    for source in dict.fromkeys((text, *alternatives)):
        slots = list(spoken_slots(source))
        if len(slots) == len(tasks) and fully_timed is None:
            fully_timed = slots
        if len(tasks) == 1 and len(slots) == 1:
            matches = {0: slots[0]}
        else:
            matches = {}
            for clause, first, last in slots:
                tokens = set(words(clause))
                scores = [len(set(words(task.title)) & tokens) for task in tasks]
                best = max(scores, default=0)
                if best and scores.count(best) == 1:
                    index = scores.index(best)
                    matches.setdefault(index, []).append((clause, first, last))
            matches = {index: candidates[0] for index, candidates in matches.items()
                       if len(candidates) == 1}

        for index, (clause, first, last) in matches.items():
            if index in resolved:
                continue
            task = tasks[index]
            if len(tasks) > 1 and len(ANCHOR.findall(clause)) == 1:
                enforce_date_context([task], clause, timezone_name, now)
            day = task.start.astimezone(zone).date()
            start = datetime.fromisoformat(f'{day}T{first}').replace(tzinfo=zone)
            if last:
                end = datetime.fromisoformat(f'{day}T{last}').replace(tzinfo=zone)
                if end == start:
                    raise HTTPException(422, 'Начало и конец совпадают. Уточните время окончания.')
                if end < start:
                    end += timedelta(days=1)
                task.end = end.astimezone(timezone.utc)
            else:
                duration = spoken_duration(clause)
                if duration is None:
                    duration = task.end - task.start if DURATION.search(clause) else timedelta(hours=1)
                task.end = start.astimezone(timezone.utc) + duration
            task.start = start.astimezone(timezone.utc)
            resolved.add(index)

    if fully_timed and len(resolved) < len(tasks):
        expected = Counter(first for _, first, _ in fully_timed)
        actual = Counter(task.start.astimezone(zone).strftime('%H:%M') for task in tasks)
        if expected != actual:
            return set(range(len(tasks))) - resolved
    return set()


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
