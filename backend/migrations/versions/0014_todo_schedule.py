from alembic import op
import sqlalchemy as sa
revision='0014'
down_revision='0013'
branch_labels=None
depends_on=None

def upgrade():
    op.add_column('todos',sa.Column('scheduled_date',sa.Date(),nullable=True))
    op.add_column('todos',sa.Column('scheduled_at',sa.DateTime(timezone=True),nullable=True))
    op.add_column('todos',sa.Column('timezone',sa.Text(),nullable=False,server_default='Asia/Tomsk'))
    op.create_index('ix_todos_scheduled_date','todos',['scheduled_date'])

def downgrade():
    op.drop_index('ix_todos_scheduled_date',table_name='todos')
    for name in ('timezone','scheduled_at','scheduled_date'):
        op.drop_column('todos',name)
