import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.plans.colloquial_time import clock_text
from app.plans.dates import SENTENCE_BREAK, words
from app.plans.schemas import PlanOption, PlanReview

UNCERTAIN = re.compile(r'\b(?:не\s+помню|не\s+уверен\w*|вроде|по-моему|возможно|кажется|может\s+быть|примерно|либо)\b', re.I)


def matching_tasks(tasks, fragment):
    tokens = set(words(fragment))
    exact = set(re.findall(r'[а-яё]+', fragment.casefold()))
    scores = [(len(set(words(task.title)) & tokens),
               len(set(re.findall(r'[а-яё]+', task.title.casefold())) & exact)) for task in tasks]
    best = max(scores, default=(0, 0))
    return [index for index, score in enumerate(scores) if score == best and best[0]]


def build_review(tasks, model_reasons, time_reviews, transcript, timezone):
    zone = ZoneInfo(timezone)
    reviews = {index: PlanReview(task_index=index, reason=model_reasons[task.title])
               for index, task in enumerate(tasks) if task.title in model_reasons}

    for fragment in SENTENCE_BREAK.split(transcript):
        if UNCERTAIN.search(fragment):
            for index in matching_tasks(tasks, fragment):
                reviews.setdefault(index, PlanReview(task_index=index, reason='В диктовке это событие прозвучало как предварительное.'))

    for issue in time_reviews:
        matches = matching_tasks(tasks, issue.fragment)
        if len(matches) != 1 and issue.choices:
            suggested = tuple(clock_text(value) for value in issue.choices[0])
            candidates = matches or range(len(tasks))
            matches_by_time = [
                index for index in candidates
                if tuple(value.astimezone(zone).strftime('%H:%M') for value in (tasks[index].start, tasks[index].end)) == suggested
            ]
            matches = matches_by_time or matches
        if len(matches) != 1:
            # A complete draft still needs confirmation if the doubtful phrase
            # could not be associated reliably with one event.
            for index in matches or range(len(tasks)):
                reviews.setdefault(index, PlanReview(task_index=index, reason='Проверьте, к какому событию относится время из диктовки.'))
            continue
        index = matches[0]
        day = tasks[index].start.astimezone(zone).date()
        midnight = datetime(day.year, day.month, day.day, tzinfo=zone)
        options = [PlanOption(start=midnight + timedelta(minutes=start), end=midnight + timedelta(minutes=end))
                   for start, end in issue.choices]
        reviews[index] = PlanReview(task_index=index, reason=issue.reason, options=options)

    return sorted(reviews.values(), key=lambda review: review.task_index)
