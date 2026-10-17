from uuid import UUID,uuid4
from sqlalchemy import String,Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped,mapped_column
from app.core.database import Base
class Command(Base):
    __tablename__='commands'
    id: Mapped[UUID]=mapped_column(primary_key=True,default=uuid4)
    text: Mapped[str]=mapped_column(Text)
    status: Mapped[str]=mapped_column(String(20),default='draft')
    operations: Mapped[list]=mapped_column(JSONB)
    note: Mapped[str]=mapped_column(Text)
    result: Mapped[dict|None]=mapped_column(JSONB,nullable=True)
