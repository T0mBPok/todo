from alembic import op
import sqlalchemy as sa
revision='0006'
down_revision='0005'
branch_labels=None
depends_on=None

def upgrade():
    for table in ('todos','tasks'):
        op.add_column(table,sa.Column('category',sa.String(40),nullable=False,server_default='important_not_urgent'))
        op.create_check_constraint('ck_'+table+'_category',table,"category IN ('important_urgent','important_not_urgent','not_important_urgent','not_important_not_urgent')")

def downgrade():
    for table in ('todos','tasks'):
        op.drop_constraint('ck_'+table+'_category',table,type_='check')
        op.drop_column(table,'category')
