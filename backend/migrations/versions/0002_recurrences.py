from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision='0002'
down_revision='0001'
branch_labels=None
depends_on=None

def upgrade():
    op.add_column('tasks',sa.Column('recurrence',postgresql.JSONB(),nullable=True))
    op.create_table('recurrence_exceptions',
        sa.Column('task_id',sa.Uuid(),sa.ForeignKey('tasks.id',ondelete='CASCADE'),primary_key=True),
        sa.Column('occurrence_start',sa.DateTime(timezone=True),primary_key=True))
    op.execute('ALTER TABLE tasks DROP CONSTRAINT tasks_no_overlap')
    op.execute("""ALTER TABLE tasks ADD CONSTRAINT tasks_no_overlap EXCLUDE USING gist (tstzrange(start, "end", '[)') WITH &&) WHERE (recurrence IS NULL)""")

def downgrade():
    op.execute('ALTER TABLE tasks DROP CONSTRAINT tasks_no_overlap')
    op.drop_table('recurrence_exceptions')
    op.drop_column('tasks','recurrence')
    op.execute("""ALTER TABLE tasks ADD CONSTRAINT tasks_no_overlap EXCLUDE USING gist (tstzrange(start, "end", '[)') WITH &&)""")
