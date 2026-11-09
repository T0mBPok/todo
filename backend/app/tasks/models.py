from datetime import datetime
from uuid import UUID, uuid4
from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, false
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base, Owned

class Task(Owned, Base):
    __tablename__ = 'tasks'
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    category: Mapped[str] = mapped_column(Text, default='important_not_urgent', server_default='important_not_urgent')
    is_fixed: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    from_google: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    is_all_day: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    title: Mapped[str] = mapped_column(String(200))
    start: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    plan_id: Mapped[UUID | None] = mapped_column(ForeignKey('plans.id'), index=True)
    recurrence: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    description: Mapped[str] = mapped_column(Text, default='', server_default='')
    series_parent_id: Mapped[UUID | None] = mapped_column(ForeignKey('tasks.id',ondelete='CASCADE'),nullable=True,index=True)
    series_original_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),nullable=True)
