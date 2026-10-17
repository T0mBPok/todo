from pydantic import BaseModel

class Transcript(BaseModel):
    text: str
    engine: str = ''
    seconds: float = 0
    warning: str = ''
