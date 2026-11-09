from alembic import op
import sqlalchemy as sa

revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('tasks', sa.Column('from_google', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('tasks', sa.Column('is_all_day', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.execute('ALTER TABLE tasks DROP CONSTRAINT tasks_no_overlap')
    op.execute("""
        ALTER TABLE tasks ADD CONSTRAINT tasks_no_overlap
        EXCLUDE USING gist (owner_id WITH =, tstzrange(start, "end", '[)') WITH &&)
        WHERE (recurrence IS NULL AND NOT from_google)
    """)


def downgrade():
    op.execute('ALTER TABLE tasks DROP CONSTRAINT tasks_no_overlap')
    op.execute("""
        ALTER TABLE tasks ADD CONSTRAINT tasks_no_overlap
        EXCLUDE USING gist (owner_id WITH =, tstzrange(start, "end", '[)') WITH &&)
        WHERE (recurrence IS NULL)
    """)
    op.drop_column('tasks', 'is_all_day')
    op.drop_column('tasks', 'from_google')
