from datetime import datetime
from uuid import UUID
from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base

class RecurrenceException(Base):
    __tablename__ = 'recurrence_exceptions'
    task_id: Mapped[UUID] = mapped_column(ForeignKey('tasks.id',ondelete='CASCADE'),primary_key=True)
    occurrence_start: Mapped[datetime] = mapped_column(DateTime(timezone=True),primary_key=True)
