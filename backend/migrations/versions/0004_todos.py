from alembic import op
import sqlalchemy as sa
revision='0004'
down_revision='0003'
branch_labels=None
depends_on=None
def upgrade():
    op.create_table('todos',sa.Column('id',sa.Uuid(),primary_key=True),sa.Column('title',sa.Text(),nullable=False),sa.Column('description',sa.Text(),nullable=False),sa.Column('completed',sa.Boolean(),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False))
def downgrade():op.drop_table('todos')
