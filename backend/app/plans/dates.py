"""Resolve explicit date anchors in speech independently of model arithmetic."""
import re
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

ORDINAL_DATE = re.compile(
    r'(?<![\w:–-])\d{1,2}(?:\s*[-–‑]\s*(?:ого|ое|го|е)(?:\s+числ[оа])?|\s+числ[оа]|\s+(?:'
    + '|'.join(MONTHS) + r'))(?:\s+(?:' + '|'.join(MONTHS) + r'))?(?:\s+\d{4}(?:\s*года)?)?(?![\w:])', re.I)


def canonical_date_anchors(text, today):
    """Turn an explicit calendar day into an ISO anchor without asking the LLM."""
    def replace(match):
        prefix=text[max(0,match.start()-30):match.start()]
        if re.search(r'(?:'+'|'.join(stem+r'[а-яё]*' for stem in WEEKDAYS)+r')\s*$',prefix,re.I):
            return match[0]  # weekday + explicit day is already handled together
        target,_=explicit_weekday_date(match[0].replace('‑','-'),today)
        return target.isoformat() if target else match[0]
    return ORDINAL_DATE.sub(replace,text)


CLOCK = r'(?<![\d:])(?:[01]?\d|2[0-3]):[0-5]\d(?![\d:])'
TIME_RANGE = re.compile(rf'\b(?:с\s+)?({CLOCK})(?:\s+до\s+|\s*[-–—]\s*)({CLOCK})', re.I)
START_TIME = re.compile(rf'\b(?:в|во|на|к)\s+({CLOCK})', re.I)
SHORT_CLOCK = re.compile(r'(?<![\d:])([01]?\d|2[0-3]):([0-5]?\d)(?![\d:])')
COMPACT_RANGE_END = re.compile(rf'({CLOCK}\s+до\s+)([01]\d|2[0-3])([0-5]\d)\b(?![.:]\d)', re.I)


DAYPART_ALIASES = {
    'утра':'утра','ут':'утра','утр':'утра',
    'дня':'дня','дн':'дня','день':'дня','ня':'дня',
    'вечера':'вечера','веч':'вечера','вечер':'вечера',
    'ночи':'ночи','ноч':'ночи','ночь':'ночи','ночью':'ночи',
}
DAYPART_TOKENS = '|'.join(sorted(DAYPART_ALIASES,key=len,reverse=True))


def normalize_clock_minutes(text):
    # Zero seconds add no information to minute-precision calendar intervals.
    text = re.sub(r'(?<![\d:])([01]?\d|2[0-3]):([0-5]?\d):0{1,2}(?![\d:])',
                  lambda m:f'{int(m[1]):02d}:{int(m[2]):02d}',text)
    text = re.sub(r'\b(с\s+)([1-9])0(?=\s+до\s+(?:[01]?\d|2[0-3]):[0-5]\d)',r'\g<1>0\2:00',text,flags=re.I)
    # Repeated minute digits and a damaged day-part token are common ASR output.
    text = re.sub(r'(?<![\d:])((?:[01]?\d|2[0-3]):([0-5]\d))\s+\2(?![\d:])',r'\1',text)
    text = re.sub(r'(?<![\d:])((?:[01]?\d|2[0-3]):[0-5]\d)\s+0ня\b',r'\1 дня',text,flags=re.I)
    # Colons identify a clock without guessing whether a dotted number is a date.
    text = re.sub(r'(?<![\d:])([01]?\d|2[0-3])\s*(?:\s*:\s*){1,3}([0-5]?\d)(?![\d:])',
                  lambda m: f'{int(m[1]):02d}:{int(m[2]):02d}',text)
    text = re.sub(r'(?<![\d:])([01]?\d|2[0-3]):0{3,}(?![\d:])',lambda m:f'{int(m[1]):02d}:00',text)
    # A named day part disambiguates a dotted clock from DD.MM.
    text = re.sub(rf'(?<![\d.])([01]?\d|2[0-3])\.([0-5]\d)(?=\s*(?:{DAYPART_TOKENS})\b)',
                  lambda m:f'{int(m[1]):02d}:{m[2]}',text,flags=re.I)

    # ASR may spell a clock as two number groups. Require a time
    # preposition or a day part so ordinary quantities remain untouched.
    text = re.sub(r'\b((?:с|до|в|во|на|к)\s+)([01]?\d|2[0-3])\s+([0-5]\d)(?![\d:]|\s*(?:руб|минут|секунд))\b',
                  r'\1\2:\3', text, flags=re.I)
    text = re.sub(r'\b([01]?\d|2[0-3])\s+([0-5]\d)(?=\s+(?:утра|дня|вечера|ночи)\b)',
                  r'\1:\2', text, flags=re.I)
    text = re.sub(r'(' + CLOCK + r')\s+ут\b\.?', r'\1 утра', text, flags=re.I)
    # ASR can leave a bare colon before a day part ("11: вечера")
    # or glue the damaged suffix "ня" to a clock ("12:00ня").
    text = re.sub(rf'(?<![\d:])([01]?\d|2[0-3])\s*:\s*(?=(?:{DAYPART_TOKENS})\b)',
                  lambda match: f'{int(match[1]):02d}:00 ', text, flags=re.I)
    text = SHORT_CLOCK.sub(lambda match: f'{int(match[1]):02d}:{int(match[2]):02d}', text)
    text = re.sub(rf'({CLOCK})\s*({DAYPART_TOKENS})\b',
                  lambda match: match[1] + ' ' + DAYPART_ALIASES[match[2].lower()],
                  text, flags=re.I)

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


DAYPART_CLOCK = re.compile(rf'({CLOCK})\s+(утра|дня|вечера|ночи)\b', re.I)


def normalize_clock_dayparts(text):
    """Keep explicit day parts when checking the model's local wall time."""
    def replace(match):
        hour, minute = map(int, match[1].split(':'))
        if hour <= 12:
            part = match[2].casefold()
            pm = part in {'дня', 'вечера'} or part == 'ночи' and 10 <= hour < 12
            hour = hour % 12 + (12 if pm else 0)
        return f'{hour:02d}:{minute:02d}'
    return DAYPART_CLOCK.sub(replace, normalize_clock_minutes(text))


def spoken_slots(text):
    from app.plans.transcript_guard import explicit_clock_text
    for sentence in SENTENCE_BREAK.split(normalize_clock_dayparts(explicit_clock_text(text))):
        sentence = DETAIL_MARKER.split(sentence, maxsplit=1)[0]
        clock_count = len(re.findall(CLOCK, sentence))
        if clock_count > 1 and re.search(r'\b(?:ой[,\s]+нет|точнее|пардон)\b', sentence, re.I):
            continue
        single_slot_size = 2 if TIME_RANGE.search(sentence) else 1
        clauses = CLAUSE_BREAK.split(sentence) if clock_count > single_slot_size else [sentence]
        fragments=[]
        for clause in clauses:
            intervals=list(TIME_RANGE.finditer(clause))
            if len(intervals)>1 and len(re.findall(CLOCK,clause))==2*len(intervals):
                # Lists need not have punctuation between adjacent events.
                # Detect whether names precede or follow the first interval.
                prefix=ORDINAL_DATE.sub(' ',ANCHOR.sub(' ',clause[:intervals[0].start()]))
                prefix=re.sub(r'\b(?:постав[а-яё]*|став[а-яё]*|добав[а-яё]*|запланиру[а-яё]*|пожалуйста|мне|меня|числ[а-яё]*|на|в|с|кажд[а-яё]*)\b|\d+',' ',prefix,flags=re.I)
                names_before=bool(words(prefix))
                for i,interval in enumerate(intervals):
                    left=intervals[i-1].end() if names_before and i else interval.start() if i else 0
                    right=interval.end() if names_before else intervals[i+1].start() if i+1<len(intervals) else len(clause)
                    fragments.append(clause[left:right])
            else:
                fragments.append(clause)
        for clause in fragments:
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
    unverifiable = set()
    ambiguous_original = set()
    for source in dict.fromkeys((text, *alternatives)):
        slots = list(spoken_slots(source))
        # A damaged explicit clock must trigger review, even when it yielded
        # no parseable slot and the model claims its answer is confident.
        for clause in re.split(r'\.(?!\d)|[!?;]|,\s*(?!\d)|\s+(?:и|потом|затем)\s+',source,flags=re.I):
            clause=DETAIL_MARKER.split(clause,maxsplit=1)[0]
            if not re.search(r'(?<!\d)\d{1,2}\s*[:./]',clause):continue
            tokens=set(words(clause))
            for index,task in enumerate(tasks):
                if not tokens & set(words(task.title)):continue
                unverifiable.add(index)
                # An LLM rewrite is not evidence for ambiguous dates/clocks or
                # invalid minutes in the original. These keep their review flag.
                if source == text and (
                    re.search(r'(?<![\d:])\d{1,2}[./]\d{1,2}(?!\d)',clause)
                    or re.search(r'\b\d{1,2}:([6-9]\d|\d{3,})(?!\d)',clause)
                    or re.search(r'\b(?:2[4-9]|[3-9]\d):\d',clause)
                    or re.search(r'\b\d{1,2}:\d{1,2}:\d',clause)
                    or re.search(rf'({CLOCK})[а-яё]+\b',clause,re.I)
                ):ambiguous_original.add(index)
        if len(slots) == len(tasks) and fully_timed is None:
            fully_timed = slots
        if len(tasks) == 1 and len(slots) == 1:
            matches = {0: slots[0]}
        elif (len(slots) == 1 and tasks and all(task.recurrence for task in tasks)
              and len({task.title.casefold() for task in tasks}) == 1):
            # One shared interval may apply to several explicitly named weekdays.
            matches = {index: slots[0] for index in range(len(tasks))}
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
            if len(tasks) > 1 and not task.recurrence and len(ANCHOR.findall(clause)) == 1:
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
        # Equal start-clock counts cannot prove event-to-slot correspondence
        # or correct end times; unmatched events still require review.
        unverifiable.update(range(len(tasks)))
    return (unverifiable - resolved) | ambiguous_original


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
    text=canonical_date_anchors(text,today)
    anchors=list(ANCHOR.finditer(text))
    if not anchors:
        return tasks
    # A date may precede or follow its event: «в четверг кафедра» and
    # «кафедра в четверг». Do not attach the latter title to the previous day.
    starts=[]
    for i, match in enumerate(anchors):
        sentence_start=max((item.end() for item in SENTENCE_BREAK.finditer(text[:match.start()])), default=0)
        if i and anchors[i-1].end() > sentence_start:
            boundaries=list(CLAUSE_BREAK.finditer(text, anchors[i-1].end(), match.start()))
            left=boundaries[-1].end() if boundaries else match.start()
        else:
            left=sentence_start
        starts.append(left)
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
        end=starts[i+1] if i+1<len(anchors) else len(text)
        fragment=text[starts[i]:match.start()]+' '+text[match.end()+consumed:end]
        segments.append((day,words(fragment)))
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
