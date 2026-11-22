from datetime import datetime, date, timezone
from uuid import UUID
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field,AwareDatetime,model_validator,field_validator,PrivateAttr
from app.core.priority import Category
from zoneinfo import ZoneInfo
from app.plans.schemas import PlanRequest
class TodoInput(BaseModel):
    category: Category = 'important_not_urgent'
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    title: str=Field(min_length=1,max_length=200)
    description: str=Field(default='',max_length=5000)
    completed: bool=False
    scheduled_date: date|None=None
    scheduled_at: AwareDatetime|None=None
    timezone: str='Asia/Tomsk'

    @field_validator('timezone')
    @classmethod
    def valid_timezone(cls, value):
        return PlanRequest.valid_zone(value)

    @model_validator(mode='after')
    def validate_schedule(self):
        if self.scheduled_at is not None:
            local_day = self.scheduled_at.astimezone(ZoneInfo(self.timezone)).date()
            if self.scheduled_date is not None and self.scheduled_date != local_day:
                raise ValueError('Дата и время задачи относятся к разным дням')
            self.scheduled_date = local_day
            self.scheduled_at = self.scheduled_at.astimezone(timezone.utc)
        return self
class TodoRead(TodoInput):
    model_config=ConfigDict(from_attributes=True)
    id: UUID
    created_at: datetime
class HistoryItem(BaseModel):
    role: Literal['user','assistant']
    text: str=Field(max_length=1500)
class VoiceRequest(PlanRequest):
    history: list[HistoryItem]=Field(default_factory=list,max_length=8)
    text: str=Field(min_length=1,max_length=6000)
class Completion(BaseModel):
    completed: bool

class Action(BaseModel):
    _invalid_schedule: bool = PrivateAttr(default=False)
    scheduled_date: date|None=None
    scheduled_at: datetime|None=None
    schedule_text: str|None=Field(default=None,max_length=1000,description='Точный фрагмент речи с датой и временем только этой задачи; не выдумывай.')
    clear_schedule: bool=False
    clear_time: bool=False
    category: Category|None=None
    action: Literal['create','update','delete','complete','reopen']
    ref: str|None=None
    title: str|None=Field(default=None,max_length=200,description='Краткая самостоятельная цель с действием. Списки предметов и подшаги вынеси в description.')
    description: str|None=Field(default=None,max_length=5000,description='Подробности цели: список покупок, подшаги, сроки и условия из речи. Не требуй отдельного слова описание.')
class Decision(BaseModel):
    actions: list[Action]=Field(default_factory=list,max_length=30)
    clarification: str|None=None
    note: str=Field(max_length=1500)
