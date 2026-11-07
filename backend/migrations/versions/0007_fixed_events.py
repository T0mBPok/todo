from alembic import op
import sqlalchemy as sa
revision='0007'
down_revision='0006'
branch_labels=None
depends_on=None
def upgrade():
    op.add_column('tasks',sa.Column('is_fixed',sa.Boolean(),nullable=False,server_default=sa.false()))
def downgrade():
    op.drop_column('tasks','is_fixed')
