from alembic import context
from app.core.database import Base, engine
from app.tasks.models import Task
from app.recurrences.models import RecurrenceException
from app.plans.models import Plan
from app.commands.models import Command

with engine.connect() as connection:
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()
