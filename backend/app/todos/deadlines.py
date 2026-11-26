"""Keep a task's last permissible date separate from its planned work date."""
import re
from fastapi import HTTPException
from app.todos.schemas import Action
from app.todos.scheduling import grounded_schedule, DATE_TOKEN

MARKER=re.compile(r'\b(?:дедлайн\w*|крайний\s+срок|срок\s+сдачи|не\s+позднее|не\s+позже)\b\s*[:—-]?\s*',re.I)
CLEAR=re.compile(r'\b(?:убери|удали|сними|без)\s+(?:дедлайн\w*|крайн\w*\s+срок\w*)\b',re.I)
BY_DATE=re.compile(r'\b(?:до|к)\s+(?=(?:'+DATE_TOKEN.pattern+r'))',re.I)


def deadline_parts(action, source, zone):
    if action.clear_deadline:
        if not CLEAR.search(source):
            raise HTTPException(422,'Уточните, нужно ли убрать дедлайн.')
        return CLEAR.sub('',source), {'deadline_date':None,'deadline_at':None,'timezone':zone}, False
    marker=MARKER.search(source)
    if marker:
        schedule_source=source[:marker.start()]
        deadline_source=source[marker.end():]
    elif BY_DATE.search(source):
        boundary=BY_DATE.search(source)
        schedule_source=source[:boundary.start()]
        deadline_source=source[boundary.start():]
    elif action.deadline_date or action.deadline_at or action.deadline_text:
        fragment=(action.deadline_text or '').strip()
        literal=bool(fragment and ' '.join(fragment.lower().split()) in ' '.join(source.lower().split()))
        if not literal or not re.search(r'\b(?:до|к)\b',fragment,re.I):
            raise HTTPException(422,'Назовите крайний срок: например «дедлайн завтра в 18:00».')
        match=re.search(re.escape(fragment),source,re.I)
        if not match:
            raise HTTPException(422,'Уточните формулировку дедлайна.')
        schedule_source=source[:match.start()]+source[match.end():]
        deadline_source=fragment
    else:
        return source,None,False
    proposal=Action(action=action.action,scheduled_date=action.deadline_date,scheduled_at=action.deadline_at)
    schedule,uncertain=grounded_schedule(proposal,deadline_source,zone)
    if not schedule['scheduled_date']:
        raise HTTPException(422,'Укажите день дедлайна, например «дедлайн в пятницу».')
    return schedule_source,{'deadline_date':schedule['scheduled_date'],
                            'deadline_at':schedule['scheduled_at'],'timezone':zone},uncertain
