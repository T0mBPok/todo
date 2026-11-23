"""Validate an LLM's transcript edit, independently of ASR spelling variants."""
import re
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


def safe_transcript_edit(original,edited):
    """Let the LLM fix wording, never silently reinterpret numeric wall clocks."""
    if temporal_signature(original)!=temporal_signature(edited):
        return False
    # Existing explicit day parts must survive; a damaged word may be restored.
    parts=lambda t:re.findall(rf'({CLOCK})\s+(утра|дня|вечера|ночи)\b',t,re.I)
    before=parts(original);after=iter(parts(edited))
    return all(any(part==candidate for candidate in after) for part in before)
