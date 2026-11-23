"""Validate an LLM's transcript edit, independently of ASR spelling variants."""
import re
from app.plans.dates import ANCHOR, CLOCK, normalize_clock_dayparts

# ASR sometimes emits zero(s) instead of letters in a word beside a clock.
# Only this non-numeric residue may lose digits; real quantities stay protected.
CLOCK_RESIDUE = re.compile(rf'({CLOCK})\s+(0+[а-яё]{{1,8}})\b', re.I)
UNIT = re.compile(r'^(?:час|ч$|мин|м$|сек|с$|руб|раз|год|лет)', re.I)


def without_zero_residue(text):
    def replace(match):
        letters=match[2].lstrip('0')
        return match[0] if UNIT.match(letters) else match[1]+' '+letters
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
