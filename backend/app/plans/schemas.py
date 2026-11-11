from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator
from app.tasks.schemas import TaskInput

class PlanRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    text: str = Field(min_length=1, max_length=6000)
    timezone: str = 'Asia/Tomsk'
    _spoken_text: str | None = PrivateAttr(default=None)
    _normalized_text: str | None = PrivateAttr(default=None)

    @field_validator('timezone')
    @classmethod
    def valid_zone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError('Неизвестный часовой пояс')
        return value

class PlanOutput(BaseModel):
    tasks: list[TaskInput] = Field(min_length=1, max_length=30)
    note: str
    normalized_text: str = ''

class PlanRead(PlanOutput):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    status: str

class ConfirmPlan(BaseModel):
    tasks: list[TaskInput] = Field(min_length=1, max_length=30)
