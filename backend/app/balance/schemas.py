from datetime import date
from uuid import UUID
from typing import Literal
from zoneinfo import ZoneInfo,ZoneInfoNotFoundError
from pydantic import BaseModel,Field,field_validator
class BalanceRequest(BaseModel):
    day: date
    timezone: str='Asia/Tomsk'
    scan_days: int=Field(default=1,ge=1,le=7)
    horizon_days: int=Field(default=3,ge=1,le=7)
    gap_minutes: int=Field(default=30,ge=0,le=120)
    start_hour: int=Field(default=9,ge=0,le=22)
    end_hour: int=Field(default=21,ge=1,le=24)
    pinned_ids: list[UUID]=Field(default_factory=list,max_length=100)
    preferences: str=Field(default='',max_length=1500)
    @field_validator('timezone')
    @classmethod
    def zone(cls,value):
        try:ZoneInfo(value)
        except (ZoneInfoNotFoundError,ValueError):raise ValueError('Неизвестный часовой пояс')
        return value
class Assessment(BaseModel):
    event_ref: str
    flexibility: Literal['fixed','flexible','coordinate']
    reason: str=Field(max_length=500)
class Move(BaseModel):
    event_ref: str
    slot_ref: str
    reason: str=Field(min_length=1,max_length=1000)
class Decision(BaseModel):
    summary: str=Field(max_length=2000)
    assessments: list[Assessment]=Field(default_factory=list,max_length=60)
    moves: list[Move]=Field(default_factory=list,max_length=3)
class Apply(BaseModel):
    proposals: list[int]=Field(min_length=1,max_length=3)
    coordination_confirmed: bool=False
