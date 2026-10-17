"""Ground names and deletion corrections in actual calendar events."""
import re
from difflib import SequenceMatcher
from app.plans.dates import ANCHOR
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
