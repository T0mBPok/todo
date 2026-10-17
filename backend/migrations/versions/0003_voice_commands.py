from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision='0003'
down_revision='0002'
branch_labels=None
depends_on=None
def upgrade():
    op.add_column('tasks',sa.Column('description',sa.Text(),nullable=False,server_default=''))
    op.add_column('tasks',sa.Column('series_parent_id',sa.Uuid(),sa.ForeignKey('tasks.id',ondelete='CASCADE'),nullable=True))
    op.add_column('tasks',sa.Column('series_original_start',sa.DateTime(timezone=True),nullable=True))
    op.create_index('ix_tasks_series_parent_id','tasks',['series_parent_id'])
    op.create_table('commands',sa.Column('id',sa.Uuid(),primary_key=True),sa.Column('text',sa.Text(),nullable=False),
        sa.Column('status',sa.String(20),nullable=False),sa.Column('operations',postgresql.JSONB(),nullable=False),
        sa.Column('note',sa.Text(),nullable=False),sa.Column('result',postgresql.JSONB(),nullable=True))
def downgrade():
    op.drop_table('commands')
    op.drop_index('ix_tasks_series_parent_id',table_name='tasks')
    op.drop_column('tasks','series_original_start')
    op.drop_column('tasks','series_parent_id')
    op.drop_column('tasks','description')
