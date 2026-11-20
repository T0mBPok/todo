from alembic import op
import sqlalchemy as sa

revision = '0012'
down_revision = '0011'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('email_challenges', sa.Column('purpose', sa.String(20), nullable=False, server_default='verify'))


def downgrade():
    op.drop_column('email_challenges', 'purpose')
