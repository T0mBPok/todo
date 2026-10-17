from datetime import datetime, timezone
from uuid import UUID
from app.recurrences.schemas import RecurrenceRule
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator, field_validator

class TaskInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default='', max_length=5000)
    start: AwareDatetime
    end: AwareDatetime
    recurrence: RecurrenceRule | None = None

    @field_validator('start', 'end')
    @classmethod
    def to_utc(cls, value):
        return value.astimezone(timezone.utc)

    @model_validator(mode='after')
    def valid_interval(self):
        if self.end <= self.start:
            raise ValueError('Окончание должно быть позже начала')
        if self.recurrence and (self.end-self.start).total_seconds()>86400:
            raise ValueError('Повторяющееся событие должно длиться не более 24 часов')
        return self

class TaskRead(TaskInput):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    plan_id: UUID | None = None
    occurrence_start: AwareDatetime | None = None
    occurrence_id: str | None = None
    series_parent_id: UUID | None = None
    series_original_start: AwareDatetime | None = None
