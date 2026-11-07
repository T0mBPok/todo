from datetime import datetime
from uuid import UUID
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field
from app.core.priority import Category
class TodoInput(BaseModel):
    category: Category = 'important_not_urgent'
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    title: str=Field(min_length=1,max_length=200)
    description: str=Field(default='',max_length=5000)
    completed: bool=False
class TodoRead(TodoInput):
    model_config=ConfigDict(from_attributes=True)
    id: UUID
    created_at: datetime
class HistoryItem(BaseModel):
    role: Literal['user','assistant']
    text: str=Field(max_length=1500)
class VoiceRequest(BaseModel):
    history: list[HistoryItem]=Field(default_factory=list,max_length=8)
    text: str=Field(min_length=1,max_length=6000)
class Action(BaseModel):
    category: Category|None=None
    action: Literal['create','update','delete','complete','reopen']
    ref: str|None=None
    title: str|None=Field(default=None,max_length=200,description='Краткая самостоятельная цель с действием. Списки предметов и подшаги вынеси в description.')
    description: str|None=Field(default=None,max_length=5000,description='Подробности цели: список покупок, подшаги, сроки и условия из речи. Не требуй отдельного слова описание.')
class Decision(BaseModel):
    actions: list[Action]=Field(default_factory=list,max_length=30)
    clarification: str|None=None
    note: str=Field(max_length=1500)
