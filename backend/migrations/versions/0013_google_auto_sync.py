from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision='0013'
down_revision='0012'
branch_labels=None
depends_on=None

def upgrade():
    op.add_column('google_connections',sa.Column('sync_enabled',sa.Boolean(),nullable=False,server_default=sa.false()))
    op.add_column('google_connections',sa.Column('next_sync_at',sa.DateTime(timezone=True)))
    op.add_column('google_connections',sa.Column('last_synced_at',sa.DateTime(timezone=True)))
    op.add_column('google_connections',sa.Column('sync_error',sa.Text()))
    op.add_column('google_connections',sa.Column('sync_conflicts',sa.Integer(),nullable=False,server_default='0'))
    op.add_column('google_connections',sa.Column('sync_partial',sa.Boolean(),nullable=False,server_default=sa.false()))
    op.create_index('ix_google_connections_next_sync_at','google_connections',['next_sync_at'])
    op.add_column('google_links',sa.Column('export_fingerprint',sa.String(64)))
    op.add_column('google_links',sa.Column('conflict',postgresql.JSONB(none_as_null=True)))

def downgrade():
    op.drop_column('google_links','conflict')
    op.drop_column('google_links','export_fingerprint')
    op.drop_index('ix_google_connections_next_sync_at','google_connections')
    for name in ('sync_partial','sync_conflicts','sync_error','last_synced_at','next_sync_at','sync_enabled'):
        op.drop_column('google_connections',name)
