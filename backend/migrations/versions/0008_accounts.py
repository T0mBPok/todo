from alembic import op
import sqlalchemy as sa

from app.users.models import LoginSession, RateBucket
from app.google_sync.models import GoogleConnection, GoogleState, GoogleLink

revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None

NEW_TABLES = (LoginSession, RateBucket, GoogleConnection, GoogleState, GoogleLink)
OWNED_TABLES = ('tasks', 'todos', 'plans', 'commands')


def upgrade():
    op.create_table('users', sa.Column('id', sa.Uuid(), primary_key=True),
                    sa.Column('email', sa.String(254), nullable=False, unique=True),
                    sa.Column('password_hash', sa.Text(), nullable=False))
    for model in NEW_TABLES:
        model.__table__.create(op.get_bind())
    for name in OWNED_TABLES:
        op.add_column(name, sa.Column('owner_id', sa.Uuid(), nullable=True))
        op.create_foreign_key(f'fk_{name}_owner', name, 'users', ['owner_id'], ['id'], ondelete='CASCADE')
        op.create_index(f'ix_{name}_owner_id', name, ['owner_id'])
    op.execute('CREATE EXTENSION IF NOT EXISTS btree_gist')
    op.execute('ALTER TABLE tasks DROP CONSTRAINT tasks_no_overlap')
    op.execute("""ALTER TABLE tasks ADD CONSTRAINT tasks_no_overlap
        EXCLUDE USING gist (owner_id WITH =, tstzrange(start, "end", '[)') WITH &&)
        WHERE (recurrence IS NULL)""")


def downgrade():
    raise RuntimeError('Восстановите резервную копию до миграции аккаунтов.')
