from alembic import op

revision = '0016'
down_revision = '0015'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('ALTER TABLE tasks DROP CONSTRAINT IF EXISTS tasks_no_overlap')


def downgrade():
    raise RuntimeError('Overlapping events may already exist. Restore the pre-migration backup before reintroducing the exclusion constraint.')
