"""Validate an LLM's transcript edit, independently of ASR spelling variants."""
import re
from difflib import SequenceMatcher
from app.plans.dates import ANCHOR, CLOCK, normalize_clock_dayparts

# ASR sometimes emits zero(s) instead of letters in a word beside a clock.
# Only this non-numeric residue may lose digits; real quantities stay protected.
CLOCK_RESIDUE = re.compile(rf'({CLOCK})\s+((?=[а-яё0]*[а-яё])[а-яё]*0[а-яё0]*)\b', re.I)
UNIT = re.compile(r'^(?:час|ч$|мин|м$|сек|с$|руб|раз|год|лет)', re.I)


def without_zero_residue(text):
    def replace(match):
        letters=match[2].replace('0','')
        return match[0] if UNIT.match(letters) else match[1]+' '+letters
    return CLOCK_RESIDUE.sub(replace,text)


def display_transcript(text):
    """Hide undecoded clock-word debris; keep the original for interpretation."""
    def replace(match):
        letters=match[2].replace('0','')
        return match[0] if UNIT.match(letters) else match[1]
    return CLOCK_RESIDUE.sub(replace,text)


def explicit_clock_text(text):
    """A damaged word cannot override an already unambiguous 24-hour clock.

    Small hours with an unknown day part remain for review: 06:00 could have
    meant six in the evening. 12:00..23:59 already specify the local hour.
    """
    def replace(match):
        letters=match[2].replace('0','')
        hour=int(match[1].split(':')[0])
        tail=text[match.end():]
        known_end=re.match(rf'\s+до\s+{CLOCK}\s+(?:утра|дня|вечера|ночи)\b',tail,re.I)
        if (hour >= 12 or known_end) and not UNIT.match(letters):
            return match[1]
        return match[0]
    return CLOCK_RESIDUE.sub(replace,text)


def temporal_signature(text):
    text=without_zero_residue(text)
    # Preserve the order too: the same bag of times can belong to wrong events.
    numbers=re.findall(r'\d+',text)
    anchors=[m.group().casefold() for m in ANCHOR.finditer(text)]
    local_clocks=re.findall(CLOCK,normalize_clock_dayparts(text))
    return numbers,anchors,local_clocks


# Preserve requested operations while allowing polite forms and equivalent verbs.
# An editor may repair wording, but cannot remove creation or change it to deletion.
COMMAND_ACTIONS = {
    'create': re.compile(r'\b(?:постав(?:ь(?:те)?|ишь|ите)|ставь(?:те)?|добав(?:ь(?:те)?|ишь|ите)|запланиру(?:й(?:те)?|ешь|ете)|созда(?:й(?:те)?|шь|дите)|внеси(?:те)?|запиши(?:те)?|закинь(?:те)?)\b', re.I),
    'delete': re.compile(r'\b(?:удал(?:и(?:те)?|ишь|ите)|убер(?:и(?:те)?|[её]шь|[её]те)|сотри(?:те)?|отмени(?:те)?|очисти(?:те)?)\b', re.I),
    'move': re.compile(r'\b(?:перенес(?:и(?:те)?|[её]шь|[её]те)|сдвинь(?:те)?|передвинь(?:те)?)\b', re.I),
    'update': re.compile(r'\b(?:измени(?:те)?|поменяй(?:те)?|замени(?:те)?)\b', re.I),
    'rename': re.compile(r'\bпереименуй(?:те)?\b', re.I),
}


def command_signature(text):
    actions = [(match.start(), action) for action, pattern in COMMAND_ACTIONS.items()
               for match in pattern.finditer(text)]
    return [action for _, action in sorted(actions)]



CONTACT_VERB = re.compile(r'\b(?:написать|напиши(?:те)?|писать|позвонить|позвони(?:те)?|звонить|ответить|ответь(?:те)?|связаться\s+с|встретиться\s+с)\s+', re.I)
NAME_WORD = re.compile(r"[а-яёa-z][а-яёa-z'-]*", re.I)
NAME_BOUNDARY = {'в','во','на','к','с','со','по','о','об','про','для','и','или','завтра',
                 'сегодня','послезавтра','потом','затем','через','после','до','мне','ему','ей'}


def literal_recipients(text):
    names = []
    for verb in CONTACT_VERB.finditer(text):
        tail = text[verb.end():]
        cursor = 0
        for word in list(NAME_WORD.finditer(tail))[:3]:
            name = word.group()
            if tail[cursor:word.start()].strip() or name.casefold() in NAME_BOUNDARY:
                break
            if name.casefold() not in {'письмо','сообщение','смс'}:
                names.append(name)
            cursor = word.end()
    return names


def restore_literal_recipients(original, edited):
    # ASR may write names in lowercase. Preserve the spoken spelling after
    # contact verbs without maintaining a dictionary of people's surnames.
    names = literal_recipients(original)
    exact = {name.casefold() for name in names}
    def replace(match):
        candidate = match.group()
        if candidate.casefold() in exact:
            return candidate
        alternatives = [name for name in names
                        if len(name) >= 4 and candidate[:4].casefold() == name[:4].casefold()
                        and SequenceMatcher(None, candidate.casefold(), name.casefold()).ratio() >= 0.8]
        if len(set(name.casefold() for name in alternatives)) != 1:
            return candidate
        name = alternatives[0]
        return name[:1].upper() + name[1:] if candidate[:1].isupper() else name
    return NAME_WORD.sub(replace, edited)

def safe_transcript_edit(original,edited):
    """Let the LLM fix wording, never silently reinterpret numeric wall clocks."""
    if any(not re.search(r'(?<!\w)' + re.escape(name) + r'(?!\w)', edited, re.I)
           for name in literal_recipients(original)):
        return False
    if command_signature(original) != command_signature(edited):
        return False
    if temporal_signature(original)!=temporal_signature(edited):
        return False
    # Existing explicit day parts must survive; a damaged word may be restored.
    parts=lambda t:re.findall(rf'({CLOCK})\s+(утра|дня|вечера|ночи)\b',t,re.I)
    before=parts(original);after=iter(parts(edited))
    return all(any(part==candidate for candidate in after) for part in before)
