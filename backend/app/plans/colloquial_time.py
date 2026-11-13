"""Resolve colloquial spoken time ranges in the user's local calendar."""
import re
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import HTTPException

from app.plans.dates import ANCHOR, CLOCK, DETAIL_MARKER, MONTHS, SENTENCE_BREAK

HOURS = {
    'часа': 1, 'одного': 1, 'двух': 2, 'трёх': 3, 'трех': 3, 'четырёх': 4,
    'четырех': 4, 'пяти': 5, 'шести': 6, 'семи': 7, 'восьми': 8, 'девяти': 9,
    'десяти': 10, 'одиннадцати': 11, 'двенадцати': 12, 'тринадцати': 13,
    'четырнадцати': 14, 'пятнадцати': 15, 'шестнадцати': 16, 'семнадцати': 17,
    'восемнадцати': 18, 'девятнадцати': 19, 'двадцати': 20, 'двадцати одного': 21,
    'двадцати двух': 22, 'двадцати трёх': 23, 'двадцати трех': 23,
}
MINUTES = {'пятнадцати': 15, 'тридцати': 30, 'сорока пяти': 45}
DAY_PART = r'утра|дня|вечера|ночи'
HOUR_FORMS = sorted(HOURS, key=len, reverse=True)
HOUR_WORD = '|'.join(HOUR_FORMS)
MINUTE_WORD = '|'.join(MINUTES)
NUMBER = r'(?:[01]?\d|2[0-3])(?::[0-5]?\d)?(?![\d:]|\.\d)'
POINT = rf'(?:{NUMBER}|(?:{HOUR_WORD})(?:\s+(?:{MINUTE_WORD}))?)(?:\s+(?:{DAY_PART}))?'
RANGE = re.compile(rf'\bс\s+({POINT})\s+до\s+({POINT})\b', re.I)
CLAUSE_BOUNDARY = re.compile(r',(?!\d)|\b(?:потом|затем|а\s+ещ[её]|и\s+ещ[её])\b', re.I)
DAY_SHIFT = re.compile(r'\b(?:работ[ауые]|рабоч\w*\s+день|смен[ауые])\b', re.I)
NIGHT = re.compile(r'\b(?:ноч\w*|вечерн\w*)\b', re.I)
DATE_OR_UNIT = re.compile(r'\s+(?:' + '|'.join(MONTHS) + r'|числа|минут|секунд|дней|лет|рублей)\b', re.I)
END_ONLY = re.compile(rf'\bдо\s+({CLOCK})', re.I)
HOUR_DURATION = re.compile(r'\bна\s+(\d{1,2}(?:[,.]\d{1,2})?)\s*час[а-я]*\b', re.I)


@dataclass
class RangeReview:
    fragment: str
    reason: str
    choices: list[tuple[int, int]]

    @property
    def message(self):
        return f'Уточните время для фразы «{self.fragment}». {self.reason}'


def possible_minutes(point):
    suffix = re.search(rf'\s+({DAY_PART})$', point, re.I)
    value = point[:suffix.start()] if suffix else point
    value = ' '.join(value.casefold().split())
    numeric = re.fullmatch(r'(\d{1,2})(?::(\d{1,2}))?', value)
    if numeric:
        hour, minute = int(numeric[1]), int(numeric[2] or 0)
    else:
        hours = next(name for name in HOUR_FORMS
                     if value == name or value.startswith(name + ' '))
        hour, minute = HOURS[hours], MINUTES.get(value[len(hours):].strip(), 0)
    if suffix and hour <= 12:
        part = suffix[1].casefold()
        is_pm = part in {'дня', 'вечера'} or part == 'ночи' and hour >= 10 and hour != 12
        return [(hour % 12 + (12 if is_pm else 0)) * 60 + minute]
    if not 1 <= hour <= 12:
        return [hour * 60 + minute]
    return [hour * 60 + minute, (hour + 12) % 24 * 60 + minute]


def clock_text(minutes):
    hour, minute = divmod(minutes % 1440, 60)
    return f'{hour:02d}:{minute:02d}'


def clauses_around(sentence, match):
    before = CLAUSE_BOUNDARY.split(sentence[:match.start()])[-1]
    after = CLAUSE_BOUNDARY.split(sentence[match.end():])[0]
    return before + match.group() + after


def same_day(clause):
    days = {word.casefold() for word in ANCHOR.findall(clause)}
    return days == {'сегодня'}


def report_review(reviews, clause, reason, choices):
    issue = RangeReview(' '.join(clause.strip(' ,.!?').split())[:160], reason, choices)
    if reviews is None:
        raise HTTPException(422, issue.message)
    reviews.append(issue)


def resolve_colloquial_ranges(text, timezone_name, *, now=None, reviews=None):
    zone = ZoneInfo(timezone_name)
    current = (now or datetime.now(zone)).astimezone(zone)
    minute_now = current.hour * 60 + current.minute
    edits = []
    boundaries = [0, *(match.end() for match in SENTENCE_BREAK.finditer(text)), len(text)]
    for left, right in zip(boundaries, boundaries[1:]):
        sentence = DETAIL_MARKER.split(text[left:right], maxsplit=1)[0]
        ranges = list(RANGE.finditer(sentence))
        for match in ranges:
            if DATE_OR_UNIT.match(sentence[match.end():]):
                continue
            if all(re.fullmatch(r'\d{1,2}:[0-5]?\d', point) for point in match.groups()):
                continue
            starts, ends = map(possible_minutes, match.groups())
            if len(starts) == len(ends) == 1:
                edits.append((left + match.start(), left + match.end(),
                              f'с {clock_text(starts[0])} до {clock_text(ends[0])}'))
                continue
            clause = clauses_around(sentence, match)
            choices = [(start, start + (end - start) % 1440) for start in starts for end in ends
                       if 0 < (end - start) % 1440 <= 12 * 60]
            if DAY_SHIFT.search(clause) and not NIGHT.search(clause):
                daytime = [(start, end) for start, end in choices
                           if 6 * 60 <= start < 12 * 60 and 15 * 60 <= end <= 21 * 60]
                choices = daytime or choices
            if same_day(clause) and len(choices) > 1:
                remaining = [(start, end) for start, end in choices if end > minute_now]
                choices = remaining or choices
            choices.sort()
            if len(choices) != 1:
                options = [f'{clock_text(start)}–{clock_text(end)}' for start, end in choices]
                reason = ('Вы имели в виду ' + ' или '.join(options) + '?' if options
                          else 'Начало и конец не удалось связать. Проверьте оба времени.')
                report_review(reviews, clause, reason, choices)
            if choices:
                start, end = choices[0]
                edits.append((left + match.start(), left + match.end(), f'с {clock_text(start)} до {clock_text(end)}'))
        for match in END_ONLY.finditer(sentence):
            if any(item.start() <= match.start() < item.end() for item in ranges):
                continue
            clause = clauses_around(sentence, match)
            hour, minute = map(int, match[1].split(':'))
            if (same_day(clause) and hour * 60 + minute < minute_now
                    and not re.search(rf'\b(?:{DAY_PART})\b', clause, re.I)):
                end = hour * 60 + minute
                duration = HOUR_DURATION.search(clause)
                duration_minutes = min(720, int(float(duration[1].replace(',', '.')) * 60)) if duration else 60
                duration_minutes = max(1, min(end, duration_minutes)) if end else duration_minutes
                choices = [(end + 720 - duration_minutes, end + 720)] if hour < 12 else []
                report_review(reviews, clause, 'В записи указано только время окончания, и оно уже прошло. Во сколько начинается событие и когда заканчивается?', choices)
                if choices:
                    start, end = choices[0]
                    edits.append((left + match.start(), left + match.end(), f'с {clock_text(start)} до {clock_text(end)}'))
    for start, end, replacement in reversed(edits):
        text = text[:start] + replacement + text[end:]
    return text

