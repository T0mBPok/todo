from datetime import datetime,timezone
from uuid import UUID,uuid4
from sqlalchemy import Text,DateTime,Boolean
from sqlalchemy.orm import Mapped,mapped_column
from app.core.database import Base
class Todo(Base):
    __tablename__='todos'
    id: Mapped[UUID]=mapped_column(primary_key=True,default=uuid4)
    category: Mapped[str] = mapped_column(Text, default='important_not_urgent', server_default='important_not_urgent')
    title: Mapped[str]=mapped_column(Text)
    description: Mapped[str]=mapped_column(Text,default='')
    completed: Mapped[bool]=mapped_column(Boolean,default=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc))
