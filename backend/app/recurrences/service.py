from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from fastapi import HTTPException
from dateutil.rrule import rrulestr

UTC=timezone.utc

def rule_of(task):
    rule=getattr(task,'recurrence',None)
    return rule.model_dump() if hasattr(rule,'model_dump') else rule

def wall_offset(first, last, zone):
    return last.astimezone(zone).replace(tzinfo=None) - first.astimezone(zone).replace(tzinfo=None)


def shift_occurrence(value, offset, zone):
    if not offset:
        return value
    local = value.astimezone(zone).replace(tzinfo=None)
    return (local + offset).replace(tzinfo=zone).astimezone(UTC)


def google_anchor(rule, start):
    source = rule.get('source_start')
    return datetime.fromisoformat(source) if source else start


def project_google_occurrence(rule, start, original):
    zone = ZoneInfo(rule['timezone'])
    return shift_occurrence(original, wall_offset(google_anchor(rule, start), start, zone), zone)


def google_schedule(rule, start, is_all_day):
    anchor = google_anchor(rule, start).astimezone(ZoneInfo(rule['timezone']))
    if is_all_day:
        anchor = anchor.replace(tzinfo=None)
    schedule = rrulestr('\n'.join(rule['rules']), dtstart=anchor, forceset=True)
    schedule.rdate(anchor)
    return schedule


def instances(task,start,end,excluded=frozenset()):
    rule=rule_of(task)
    if not rule:
        if task.start<end and task.end>start:
            yield task.start,task.end
        return
    zone=ZoneInfo(rule['timezone'])
    anchor=task.start.astimezone(zone)
    duration=task.end-task.start
    if rule['frequency'] == 'google':
        all_day = task.is_all_day
        schedule = google_schedule(rule, task.start, all_day)
        offset = wall_offset(google_anchor(rule, task.start), task.start, zone)
        lower, upper = start - duration, end
        if offset:
            # The inverse wall-clock shift can cross a daylight saving transition.
            lower = shift_occurrence(lower, -offset, zone) - timedelta(days=1)
            upper = shift_occurrence(upper, -offset, zone) + timedelta(days=1)
        if all_day:
            lower = lower.astimezone(UTC).replace(tzinfo=None)
            upper = upper.astimezone(UTC).replace(tzinfo=None)
        for occurrence in schedule.between(lower, upper, inc=True):
            occurrence = occurrence.replace(tzinfo=UTC) if all_day else occurrence.astimezone(UTC)
            occurrence = shift_occurrence(occurrence, offset, zone)
            finish = occurrence + duration
            if occurrence < end and finish > start and occurrence not in excluded:
                yield occurrence, finish
        return
    step=7 if rule['frequency']=='weekly' else 1
    index=max(0,((start.astimezone(zone).date()-anchor.date()).days-2)//step)
    while True:
        day=anchor.date()+timedelta(days=index*step)
        local=datetime.combine(day,anchor.timetz()).replace(tzinfo=zone)
        occurrence=local.astimezone(UTC)
        if occurrence>=end:
            break
        finish=occurrence+duration
        if finish>start and occurrence not in excluded:
            yield occurrence,finish
        index+=1

def overlaps(first,second,exceptions):
    a_rule,b_rule=rule_of(first),rule_of(second)
    a_ex=exceptions.get(getattr(first,'id',None),set())
    b_ex=exceptions.get(getattr(second,'id',None),set())
    if not a_rule and not b_rule:
        return first.start<second.end and first.end>second.start
    if not a_rule:
        return any(True for _ in instances(second,first.start,first.end,b_ex))
    if not b_rule:
        return any(True for _ in instances(first,second.start,second.end,a_ex))
    # Weekly/daily phases repeat; include seasonal timezone shifts and skip
    # all explicitly deleted occurrences before checking a full two-year cycle.
    start=max(first.start,second.start)
    excluded_dates=list(a_ex|b_ex)
    end=max([start,*excluded_dates])+timedelta(days=732)
    left=list(instances(first,start-timedelta(days=1),end,a_ex))
    right=list(instances(second,start-timedelta(days=1),end,b_ex))
    i=j=0
    while i<len(left) and j<len(right):
        if left[i][0]<right[j][1] and left[i][1]>right[j][0]:
            return True
        if left[i][1]<=right[j][1]: i+=1
        else: j+=1
    return False

def validate_conflicts(candidates,existing,exceptions):
    checked=list(existing)
    for candidate in candidates:
        for other in checked:
            if overlaps(candidate,other,exceptions):
                zone=ZoneInfo((rule_of(candidate) or rule_of(other) or {'timezone':'Asia/Tomsk'})['timezone'])
                begin=other.start.astimezone(zone)
                raise HTTPException(409,f'«{candidate.title}» пересекается с «{other.title}» ({begin:%d.%m.%Y %H:%M}'+(' и последующие повторения' if rule_of(other) else '')+'). Если нужно повторять существующую задачу, скажите «сделай её повторяющейся», либо выберите другое время.')
        checked.append(candidate)

def require_occurrence(task,start):
    for value, finish in instances(task,start,start+timedelta(seconds=1)):
        if value == start:
            return finish
    raise HTTPException(422,'Эта дата не является повторением выбранной серии.')
