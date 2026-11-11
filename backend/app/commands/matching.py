"""Ground names and deletion corrections in actual calendar events."""
import re
from difflib import SequenceMatcher
from app.plans.dates import ANCHOR, CLOCK, normalize_clock_minutes
from app.commands.schemas import Interpretation,Operation

ALIASES={'пару':'пара','пары':'пара','паре':'пара','парой':'пара','универ':'университет','универе':'университет','универа':'университет','университете':'университет','университета':'университет','валибол':'волейбол','волейболу':'волейбол','боскибол':'баскетбол','баскетболу':'баскетбол'}
STOP={'задача','задачу','задачи','событие','события','это','эту','эта','по','на','во','в','из','все','всё','мне','меня','пожалуйста','только'}
def tokens(value):
    return [ALIASES.get(w,w) for w in re.findall(r'[а-яёa-z0-9]+',value.lower().replace('ё','е')) if w not in STOP and len(w)>1]
def score_name(target,title):
    wanted=tokens(target);actual=tokens(title)
    if not wanted or not actual:return 0
    def stem(w):return w[:5] if len(w)>5 else w
    left={stem(w) for w in wanted};right={stem(w) for w in actual}
    if left<=right:return 1.0
    values=[max(SequenceMatcher(None,w,t).ratio() for t in actual) for w in wanted]
    if min(values)<0.75:return 0
    return sum(values)/len(values)*0.95

# A deliberately narrow form: one named event, one relative day, one start time.
_TIMED_DELETE = re.compile(
    r'(?:(?P<verb>убери|удали)\s+)?(?P<day>сегодня|завтра|послезавтра)\s+'
    r'(?P<title>[\w -]+?)\s+(?:с|в)\s+'
    r'(?P<clock>(?:[01]\d|2[0-3]):[0-5]\d|час(?:а)?\s+ночи)'
    r'(?:\s+(?P<last>убери|удали))?[.!]?', re.I,
)


def timed_deletion(text):
    match = _TIMED_DELETE.fullmatch(normalize_clock_minutes(text.strip()))
    if not match or bool(match['verb']) == bool(match['last']):
        return None
    title = match['title']
    if ANCHOR.search(title) or re.search(
        r'\b(?:и|или|кроме|вс[еёю]|сери\w*|повтор\w*|убери|удали|добавь|перенеси|измени)\b', title, re.I,
    ):
        return None
    clock = match['clock']
    return match['day'], title, clock if ':' in clock else '01:00'


_CREATE_TIME = (
    rf'(?:с\s+(?P<start>{CLOCK})\s+до\s+(?P<end>{CLOCK})'
    rf'|(?:на|в)\s+(?P<single>{CLOCK})(?:\s+(?P<period>утра|дня|вечера|ночи))?)'
)

_TIMED_CREATE = re.compile(
    rf'(?:поставь|запланируй|добавь)\s+(?:мне\s+)?(?P<title>[\w -]+?)\s+'
    rf'(?:на\s+)?(?P<day>сегодня|завтра|послезавтра)\s+{_CREATE_TIME}[.!]?',
    re.I,
)


_TIMED_CREATE_DAY_FIRST = re.compile(
    rf'(?:поставь|запланируй|добавь)\s+(?:мне\s+)?(?:на\s+)?(?P<day>сегодня|завтра|послезавтра)\s+'
    rf'(?P<title>[\w -]+?)\s+{_CREATE_TIME}[.!]?', re.I,
)


def timed_creation(text):
    text = normalize_clock_minutes(text.strip())
    match = _TIMED_CREATE_DAY_FIRST.fullmatch(text) or _TIMED_CREATE.fullmatch(text)
    if not match:
        return None
    title = match['title'].strip()
    if not tokens(title) or ANCHOR.search(title) or re.search(
        r'\b(?:и|или|потом|кажд\w*|повтор\w*|убери|удали|добавь|перенеси|измени|точнее|лучше)\b', title, re.I,
    ):
        return None
    if title.lower() == 'тренировку':
        title = 'Тренировка'
    else:
        title = title[:1].upper() + title[1:]
    if match['single']:
        hour, minute = map(int, match['single'].split(':'))
        period = (match['period'] or '').lower()
        if period in {'дня', 'вечера'} and 1 <= hour < 12:
            hour += 12
        elif period == 'ночи' and hour == 12:
            hour = 0
        elif period == 'утра' and hour >= 12:
            return None
        return match['day'], title, f'{hour:02d}:{minute:02d}', None
    return match['day'], title, match['start'], match['end']


def exact_title(target, title):
    def normalized(value):
        return ['тренировка' if word in {'тренировку', 'тренировки', 'тренировке'} else word
                for word in tokens(value)]
    return bool(normalized(target)) and normalized(target) == normalized(title)


def deletion_request(request):
    text=request.text.strip()
    action=re.search(r'\b(?:удал[ия][а-яё]*|убери(?:те)?|убер[её](?:шь|те)|убрать|убрал[аио]?|убира(?:й(?:те)?|ть|л[аио]?)|сотри(?:те)?|стереть|очист[ия][а-яё]*)\b',text,re.I)
    if not action:return None
    # A correction replaces the object, while an earlier day stays in context.
    dates=list(ANCHOR.finditer(text));day=dates[-1].group() if dates else None
    exception=re.search(r'\bвс[её](?:\s+(?:задачи|события|дела))?\s*,?\s*кроме\s+',text,re.I)
    if exception:
        # Last restatement wins; do not swallow subsequent commands into a name.
        marker=list(re.finditer(r'\bкроме\s+',text,re.I))[-1]
        excluded=text[marker.end():]
        excluded=re.split(r'[.!?;\n]|,?\s+\b(?:надо|нужно|всё\s+остальное|все\s+остальное|убери|убрать|удали|ой|точнее)\b',excluded,maxsplit=1,flags=re.I)[0]
        excluded=ANCHOR.sub('',excluded).strip(' ,.!?')
        if not excluded:return None
        return Interpretation(intent='manage',operations=[Operation(operation='delete',target='',date_reference=day,all_matches=True,exclude_target=excluded,scope='occurrence')])
    # Keep complex update/delete mixtures in the model interpreter.
    if re.search(r'перенес|измени|переимен|добав|замени',text,re.I):return None
    tail=text[action.end():]
    corrections=re.split(r'\b(?:ой|нет|точнее|лучше)\b',tail,flags=re.I)
    if len(corrections)>1:tail=corrections[-1]
    bulk=bool(re.search(r'\bвс[её]\b',tail,re.I))
    explicit_series=bool(re.search(r'вс[еюя].*сери|все повтор',text,re.I))
    # Multiple named objects need separate model operations.
    if re.search(r'\sи\s',tail,re.I) and not bulk:return None
    target=ANCHOR.sub('',tail)
    target=re.sub(r'\b(?:вс[её]|задачи|события|дела|только|ближайш[а-яё]*|всю|серию|повторения)\b','',target,flags=re.I).strip(' ,.!?')
    # Explicit times are parsed by the model; never treat them as part of a title.
    if re.search(r'\d|час|вечер|утр|полдень',target,re.I):return None
    if not tokens(target) and not bulk:return None
    return Interpretation(intent='manage',operations=[Operation(operation='delete',target=target,date_reference=day,all_matches=bulk,nearest=bool(re.search(r'ближайш',text,re.I)),scope='series' if explicit_series else 'occurrence' if day else 'unspecified')])
