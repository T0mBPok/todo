from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('plans',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('timezone', sa.String(100), nullable=False),
        sa.Column('tasks', postgresql.JSONB(), nullable=False),
        sa.Column('note', sa.Text(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    op.create_table('tasks',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('start', sa.DateTime(timezone=True), nullable=False),
        sa.Column('end', sa.DateTime(timezone=True), nullable=False),
        sa.Column('plan_id', sa.Uuid(), sa.ForeignKey('plans.id')),
        sa.CheckConstraint('"end" > start', name='task_valid_interval'),
        sa.CheckConstraint("length(trim(title)) > 0", name='task_nonempty_title'))
    op.create_index('ix_tasks_start', 'tasks', ['start'])
    op.create_index('ix_tasks_plan_id', 'tasks', ['plan_id'])
    op.execute("""ALTER TABLE tasks ADD CONSTRAINT tasks_no_overlap EXCLUDE USING gist (tstzrange(start, "end", '[)') WITH &&)""")

def downgrade():
    op.drop_table('tasks')
    op.drop_table('plans')
