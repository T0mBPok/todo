import re
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from fastapi import HTTPException
from app.balance.dao import BalanceDAO
from app.balance.ai import analyze
from app.balance.slots import free_slots,load_by_day,fits,move_benefit
from app.tasks.service import TaskService,calendar_lock
from app.tasks.schemas import TaskRead,TaskInput
from app.todos.dao import TodoDAO

class BalanceService:
    def __init__(self,session):self.session=session;self.tasks=TaskService(session);self.dao=BalanceDAO(session)
    def prepare(self,request):
        if request.end_hour<=request.start_hour:raise HTTPException(422,'Окончание дня должно быть позже начала.')
        zone=ZoneInfo(request.timezone);now=datetime.now(zone)
        start=datetime.combine(request.day,datetime.min.time(),zone);end=start+timedelta(days=request.horizon_days+request.scan_days)
        if end<=now:raise HTTPException(422,'Выберите текущий или будущий день.')
        events=[event for event in self.tasks.list(start,end) if not event.is_all_day]
        source=[event for event in events if request.day<=event.start.astimezone(zone).date()<request.day+timedelta(days=request.scan_days) and event.start>now]
        loads=load_by_day(events,request.model_copy(update={'horizon_days':request.horizon_days+request.scan_days-1}))
        if len(source)>60:raise HTTPException(422,'В выбранном дне больше 60 событий. Сначала уточните расписание вручную.')
        if not source:return {'id':None,'summary':'В выбранном дне нет предстоящих событий с указанным временем. Задачи без времени остаются в списке дел.','proposals':[],'load':loads,'assessments':[]}
        mapping={f'E{i+1}':event for i,event in enumerate(source)};slots={};source_values=[]
        for ref,event in mapping.items():
            pinned=event.is_fixed or (event.recurrence and event.recurrence.frequency=='google') or event.id in request.pinned_ids or event.category=='important_urgent' or bool(re.search(r'университет|универе|экзамен|лекци|^пара(?:\s|$)',event.title,re.I))
            source_values.append({'ref':ref,'title':event.title,'description':event.description,'category':event.category,'start':event.start.astimezone(zone).isoformat(),'end':event.end.astimezone(zone).isoformat(),'recurrence':event.recurrence.model_dump() if event.recurrence else None,'pinned':pinned})
            if not pinned:
                for slot_start,slot_end in free_slots(event,events,request.model_copy(update={'day':event.start.astimezone(zone).date()}),now):
                    source_load=next(item for item in loads if item['day']==event.start.astimezone(zone).date().isoformat())
                    target_load=next(item for item in loads if item['day']==slot_start.date().isoformat())
                    if re.search(r'друз|другом|встреч|созвон',event.title,re.I) and abs((slot_start.hour+slot_start.minute/60)-(event.start.astimezone(zone).hour+event.start.astimezone(zone).minute/60))>3:continue
                    benefit=move_benefit(event,slot_start,slot_end,events,request)
                    if benefit is None:continue
                    key=f'S{len(slots)+1}';slots[key]={'ref':key,'event_ref':ref,'start':slot_start.isoformat(),'end':slot_end.isoformat(),'benefit':benefit}
        # Avoid postponing a flexible activity for a week for a marginal score gain.
        for ref in mapping:
            candidates=[value for value in slots.values() if value['event_ref']==ref]
            if not candidates:continue
            best=max(value['benefit']['improvement_percent'] for value in candidates)
            comparable=[value for value in candidates if value['benefit']['improvement_percent']>=best-5]
            nearest=min(datetime.fromisoformat(value['start']).date() for value in comparable)
            slots={key:value for key,value in slots.items() if value['event_ref']!=ref or (datetime.fromisoformat(value['start']).date()==nearest and value['benefit']['improvement_percent']>=best-5)}
        # Preserve important work when a less important event in the same day can move.
        lower_days={mapping[slot['event_ref']].start.astimezone(zone).date() for slot in slots.values() if mapping[slot['event_ref']].category.startswith('not_important_')}
        slots={key:slot for key,slot in slots.items() if not (mapping[slot['event_ref']].category.startswith('important_') and mapping[slot['event_ref']].start.astimezone(zone).date() in lower_days)}
        if not slots:return {'id':None,'summary':'Заметного улучшения расписания не найдено. Учитываю нагрузку после переноса, плотность дел и перерывы; два разнесённых события сами по себе не считаются перегрузкой.','proposals':[],'load':loads,'assessments':[]}
        todos=[{'title':task.title,'description':task.description,'category':task.category} for task in TodoDAO(self.session).list() if not task.completed][:60]
        context={'now':now.isoformat(),'timezone':request.timezone,'source_day':request.day.isoformat(),'scan_days':request.scan_days,'preferences':request.preferences,'min_break_minutes':request.gap_minutes,'load':loads,'source_events':source_values,
            'calendar':[{'title':event.title,'category':event.category,'start':event.start.astimezone(zone).isoformat(),'end':event.end.astimezone(zone).isoformat()} for event in events],
            'unscheduled_tasks':todos,'allowed_slots':list(slots.values())}
        decision=analyze(context)
        assessments={item.event_ref:item for item in decision.assessments}
        if set(assessments)!=set(mapping) or len(assessments)!=len(decision.assessments):raise HTTPException(502,'Модель не оценила все события выбранного дня. Календарь не изменён.')
        proposals=[];chosen=set();reserved=[];simulated=list(events);gap=timedelta(minutes=request.gap_minutes)
        for move in decision.moves:
            if move.event_ref not in mapping or move.slot_ref not in slots:raise HTTPException(502,'Модель выбрала неизвестное событие или слот.')
            event=mapping[move.event_ref];slot=slots[move.slot_ref];assessment=assessments[move.event_ref]
            if slot['event_ref']!=move.event_ref or move.event_ref in chosen:raise HTTPException(502,'Модель перепутала слоты или повторила перенос.')
            if next(item['pinned'] for item in source_values if item['ref']==move.event_ref) or assessment.flexibility=='fixed':raise HTTPException(502,'Модель предложила перенос закреплённого или срочного события. Календарь не изменён.')
            slot_start=datetime.fromisoformat(slot['start']);slot_end=datetime.fromisoformat(slot['end'])
            if not fits(slot_start,slot_end,reserved,gap):raise HTTPException(502,'Предложенные переносы не оставляют достаточно свободного времени.')
            benefit=move_benefit(event,slot_start,slot_end,simulated,request)
            if benefit is None:continue
            simulated=[e for e in simulated if not (getattr(e,'id',None)==event.id and e.start==event.start) ]
            changed=TaskInput(category=event.category,title=event.title,description=event.description,start=slot_start,end=slot_end)
            reserved.append(changed);simulated.append(changed);chosen.add(move.event_ref)
            source_load=next(item for item in loads if item['day']==event.start.astimezone(zone).date().isoformat())
            target_load=next(item for item in loads if item['day']==slot_start.date().isoformat())
            minutes=round((event.end-event.start).total_seconds()/60)
            needs_agreement=assessment.flexibility=='coordinate' or bool(re.search(r'друз|другом|встреч|созвон',event.title,re.I))
            meaning='Новое время встречи нужно согласовать с участниками.' if needs_agreement else 'ИИ оценил событие как гибкое по времени.'
            explanation=f"{meaning} Занятость исходного дня: {benefit['source_before']['minutes']} → {benefit['source_after']['minutes']} мин; нового дня: {benefit['target_before']['minutes']} → {benefit['target_after']['minutes']} мин. Условная оценка нагрузки двух дней снизится на {benefit['improvement_percent']}%. Учтены длительность дел, плотные блоки и недостаток перерывов."
            proposals.append({'entity':'balance','snapshot':event.model_dump(mode='json'),'new_start':slot['start'],'new_end':slot['end'],'gap_minutes':request.gap_minutes,'timezone':request.timezone,'benefit':benefit,'reason':explanation,'assessment':assessment.reason,'needs_agreement':needs_agreement})
        summary=f'Просмотрено {request.scan_days} дн. расписания. '+(f'Нашёл вариантов переноса: {len(proposals)}. Они помогут разгрузить день и сохранить время для важных дел.' if proposals else 'Подходящих переносов не нашёл. Сохраняю расписание как есть.')
        result={'summary':summary,'proposals':proposals,'load':loads,'assessments':[{'title':mapping[ref].title,**item.model_dump()} for ref,item in assessments.items()]}
        if not proposals:return {'id':None,**result}
        command=self.dao.add(proposals,summary)
        return {'id':command.id,**result}

    def apply(self,id,data):
        calendar_lock(self.session);command=self.dao.get(id)
        if not command or any(op.get('entity')!='balance' for op in command.operations):raise HTTPException(404,'Предложение балансировки не найдено.')
        indices=data.proposals
        if len(set(indices))!=len(indices) or any(i<0 or i>=len(command.operations) for i in indices):raise HTTPException(422,'Проверьте выбранные переносы.')
        if command.status=='executed':
            if sorted(command.result['selection'])!=sorted(indices):raise HTTPException(409,'Этот план уже применён с другим выбором. Запустите анализ заново.')
            return command.result
        changed=[]
        try:
            for index in indices:
                proposal=command.operations[index];snapshot=TaskRead.model_validate(proposal['snapshot'])
                if proposal['needs_agreement'] and not data.coordination_confirmed:raise HTTPException(422,'Подтвердите, что новое время согласовано с участниками встречи.')
                current=next((event for event in self.tasks.list(snapshot.start,snapshot.end) if event.id==snapshot.id and event.start==snapshot.start),None)
                if current is None or any(getattr(current,key)!=getattr(snapshot,key) for key in ['title','description','end','category','recurrence','is_fixed']):raise HTTPException(409,'Событие уже изменилось. Запустите анализ заново.')
                if current.is_fixed:raise HTTPException(409,'Событие закреплено: перенос запрещён. Обновите предложения.')
                new_start=datetime.fromisoformat(proposal['new_start']);new_end=datetime.fromisoformat(proposal['new_end'])
                if new_start<=datetime.now(ZoneInfo('UTC')):raise HTTPException(409,'Предложенное время уже прошло. Запустите анализ заново.')
                gap=timedelta(minutes=proposal['gap_minutes'])
                others=[event for event in self.tasks.list(new_start-gap,new_end+gap) if not event.is_all_day and not (event.id==snapshot.id and event.start==snapshot.start)]
                if not fits(new_start,new_end,others,gap):raise HTTPException(409,'Предложенное время уже занято или не оставляет нужного перерыва. Запустите анализ заново.')
                from app.balance.schemas import BalanceRequest
                check=BalanceRequest(day=snapshot.start.astimezone(ZoneInfo(proposal.get('timezone','Asia/Tomsk'))).date(),timezone=proposal.get('timezone','Asia/Tomsk'),gap_minutes=proposal['gap_minutes'])
                zone=ZoneInfo(check.timezone)
                begin=datetime.combine(check.day,datetime.min.time(),zone)
                finish=datetime.combine(new_start.astimezone(zone).date()+timedelta(days=1),datetime.min.time(),zone)
                if move_benefit(current,new_start,new_end,[event for event in self.tasks.list(begin,finish) if not event.is_all_day],check) is None:raise HTTPException(409,'Расписание изменилось: перенос больше не даёт заметного улучшения. Обновите предложения.')
                payload=TaskInput(category=snapshot.category,title=snapshot.title,description=snapshot.description,start=new_start,end=new_end,recurrence=snapshot.recurrence)
                task=self.tasks.update(snapshot.id,payload,scope='occurrence' if snapshot.recurrence or snapshot.series_parent_id else None,occurrence_start=snapshot.occurrence_start,commit_changes=False)
                changed.append(TaskRead.model_validate(task).model_dump(mode='json'))
            result={'tasks':changed,'selection':indices,'note':'Выбранные события перенесены. Остальной календарь сохранён.'}
            command.status='executed';command.result=result;self.session.commit();return result
        except Exception:self.session.rollback();raise
