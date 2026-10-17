from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pydantic import BaseModel, ConfigDict, field_validator

class RecurrenceRule(BaseModel):
    model_config = ConfigDict(extra='forbid')
    frequency: Literal['daily','weekly']
    timezone: str = 'Asia/Tomsk'

    @field_validator('timezone')
    @classmethod
    def valid_timezone(cls,value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError,ValueError):
            raise ValueError('Неизвестный часовой пояс повторения')
        return value
