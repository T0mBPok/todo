from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
revision='0005'
down_revision='0004'
branch_labels=None
depends_on=None
def upgrade():
    op.create_table('vk_import_jobs',sa.Column('id',sa.Uuid(),primary_key=True),sa.Column('status',sa.String(20),nullable=False),sa.Column('progress',JSONB(),nullable=False),sa.Column('proposals',JSONB(),nullable=False),sa.Column('error',sa.Text(),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False))
    op.create_table('vk_imported_items',sa.Column('fingerprint',sa.String(64),primary_key=True),sa.Column('kind',sa.String(20),nullable=False),sa.Column('target_id',sa.Uuid(),nullable=False))
def downgrade():op.drop_table('vk_imported_items');op.drop_table('vk_import_jobs')
