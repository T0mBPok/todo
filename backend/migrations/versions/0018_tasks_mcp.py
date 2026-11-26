from alembic import op
import sqlalchemy as sa

revision = '0018'
down_revision = '0017'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('google_connections', sa.Column('mcp_refresh_token', sa.Text(), nullable=True))
    op.add_column('google_connections', sa.Column('mcp_migrated', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('google_states', sa.Column('provider', sa.String(16), nullable=False, server_default='google'))


def downgrade():
    op.drop_column('google_states', 'provider')
    op.drop_column('google_connections', 'mcp_migrated')
    op.drop_column('google_connections', 'mcp_refresh_token')
