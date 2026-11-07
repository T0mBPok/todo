from datetime import datetime,timedelta
from zoneinfo import ZoneInfo

def fits(start,end,events,gap):
    return not any(start<event.end+gap and end>event.start-gap for event in events)

def free_slots(event,events,request,now):
    zone=ZoneInfo(request.timezone);duration=event.end-event.start;gap=timedelta(minutes=request.gap_minutes)
    result=[]
    for offset in range(1,request.horizon_days+1):
        day=request.day+timedelta(days=offset)
        start=datetime.combine(day,datetime.min.time(),zone)+timedelta(hours=request.start_hour)
        end=datetime.combine(day,datetime.min.time(),zone)+timedelta(hours=request.end_hour)
        valid=[];point=start
        while point+duration<=end:
            if point>now and fits(point,point+duration,events,gap):valid.append(point)
            point+=timedelta(minutes=30)
        picked=[]
        # Provide several times of day so AI can consider whether an activity fits them.
        for hour in [event.start.astimezone(zone).hour,18,9]:
            if not valid:break
            best=min(valid,key=lambda value:abs((value.hour+value.minute/60)-hour))
            if best not in picked:picked.append(best)
        for value in picked:
            result.append((value,value+duration))
    return result

def load_by_day(events,request):
    zone=ZoneInfo(request.timezone);result=[]
    for offset in range(request.horizon_days+1):
        day=request.day+timedelta(days=offset);start=datetime.combine(day,datetime.min.time(),zone);end=start+timedelta(days=1)
        values=[e for e in events if e.start<end and e.end>start]
        minutes=round(sum((min(e.end,end)-max(e.start,start)).total_seconds()/60 for e in values))
        important=sum(e.category.startswith('important_') for e in values)
        ordered=sorted(values,key=lambda e:e.start)
        consecutive=sum(a.category.startswith('important_') and b.category.startswith('important_') and 0<=(b.start-a.end).total_seconds()<request.gap_minutes*60 for a,b in zip(ordered,ordered[1:]))
        result.append({'day':day.isoformat(),'count':len(values),'minutes':minutes,'important':important,'consecutive_important':consecutive})
    return result


def day_pressure(events,day,request):
    """Heuristic, not a claim about personal fatigue. Long breaks split dense chains."""
    zone=ZoneInfo(request.timezone)
    start=datetime.combine(day,datetime.min.time(),zone);end=start+timedelta(days=1)
    intervals=sorted((max(e.start,start),min(e.end,end)) for e in events if e.start<end and e.end>start)
    minutes=sum((b-a).total_seconds()/60 for a,b in intervals)
    deficit=0;chain=0;longest=0;previous=None
    for a,b in intervals:
        gap=(a-previous).total_seconds()/60 if previous else float('inf')
        duration=(b-a).total_seconds()/60
        if gap<request.gap_minutes:
            deficit+=max(0,request.gap_minutes-max(0,gap));chain+=duration
        else:chain=duration
        longest=max(longest,chain);previous=b
    dense_excess=max(0,longest-120)
    return {'minutes':round(minutes),'count':len(intervals),'short_break_minutes':round(deficit),
        'dense_minutes':round(longest),'score':minutes**2+120*deficit+dense_excess**2,
        'busy':minutes>=360 or (len(intervals)>=4 and minutes>=240) or (len(intervals)>=2 and longest>=150)}

def move_benefit(event,new_start,new_end,events,request):
    from types import SimpleNamespace
    zone=ZoneInfo(request.timezone);source_day=event.start.astimezone(zone).date();target_day=new_start.astimezone(zone).date()
    if (event.end-timedelta(microseconds=1)).astimezone(zone).date()!=source_day:return None
    before_source=day_pressure(events,source_day,request);before_target=day_pressure(events,target_day,request)
    if source_day==target_day or not before_source['busy']:return None
    remaining=[e for e in events if not (getattr(e,'id',None)==getattr(event,'id',None) and e.start==event.start and e.end==event.end)]
    after=remaining+[SimpleNamespace(start=new_start,end=new_end)]
    after_source=day_pressure(after,source_day,request);after_target=day_pressure(after,target_day,request)
    before=before_source['score']+before_target['score'];after_score=after_source['score']+after_target['score']
    # Reject swaps of the same burden and marginal improvements. Do not create tighter breaks at destination.
    if before-after_score<max(1800,before*.1) or after_target['short_break_minutes']>before_target['short_break_minutes']:return None
    return {'source_before':before_source,'source_after':after_source,'target_before':before_target,'target_after':after_target,'improvement_percent':round(100*(before-after_score)/before)}
