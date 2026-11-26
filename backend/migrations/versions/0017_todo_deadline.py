from alembic import op
import sqlalchemy as sa

revision = '0017'
down_revision = '0016'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('todos', sa.Column('deadline_date', sa.Date(), nullable=True))
    op.add_column('todos', sa.Column('deadline_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index('ix_todos_deadline_date', 'todos', ['deadline_date'])


def downgrade():
    op.drop_index('ix_todos_deadline_date', table_name='todos')
    op.drop_column('todos', 'deadline_at')
    op.drop_column('todos', 'deadline_date')
