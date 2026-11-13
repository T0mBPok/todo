from datetime import datetime, timezone
from uuid import UUID, uuid4
from sqlalchemy import DateTime, String, Text, text as sql_text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base, Owned

class Plan(Owned, Base):
    __tablename__ = 'plans'
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    text: Mapped[str] = mapped_column(Text)
    timezone: Mapped[str] = mapped_column(String(100))
    tasks: Mapped[list] = mapped_column(JSONB)
    review: Mapped[list] = mapped_column(JSONB, default=list, server_default=sql_text("'[]'::jsonb"))
    note: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default='draft')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
