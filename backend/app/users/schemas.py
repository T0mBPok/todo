from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class ChallengeInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    challenge: str = Field(pattern=r'^[A-Za-z0-9_-]{43}$')


class CodeInput(ChallengeInput):
    code: str = Field(pattern=r'^[0-9]{8}$')


class Credentials(BaseModel):
    model_config = ConfigDict(extra='forbid')
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)

    @field_validator('email')
    @classmethod
    def normalize_email(cls, value):
        return value.casefold()
