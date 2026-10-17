from typing import Literal
from uuid import UUID
from pydantic import BaseModel,Field,AwareDatetime
from app.plans.schemas import PlanRequest
class HistoryItem(BaseModel):
    role: Literal['user','assistant']
    text: str=Field(max_length=1500)
class CommandRequest(PlanRequest):
    calendar_start: AwareDatetime|None=None
    calendar_end: AwareDatetime|None=None
    history: list[HistoryItem]=Field(default_factory=list,max_length=8)
    context_task_id: UUID|None=None
    context_occurrence_start: AwareDatetime|None=None
class Operation(BaseModel):
    operation: Literal['update','delete']
    target: str
    date_reference: str|None=None
    time_reference: str|None=None
    all_matches: bool=False
    exclude_target: str|None=None
    nearest: bool=False
    scope: Literal['occurrence','series','unspecified']='unspecified'
    new_recurrence: Literal['daily','weekly']|None=None
    new_title: str|None=Field(default=None,max_length=200)
    description: str|None=Field(default=None,max_length=5000)
    append_description: bool=False
    new_time: str|None=None
    new_date_reference: str|None=None
    duration_minutes: int|None=Field(default=None,ge=1,le=10080)
class Interpretation(BaseModel):
    intent: Literal['create','manage']
    operations: list[Operation]=Field(default_factory=list,max_length=30)
class Choice(BaseModel):
    candidate: int=Field(ge=0)
    scope: Literal['occurrence','series']|None=None
class Execute(BaseModel):
    choices: list[Choice]=Field(min_length=1,max_length=30)
